#include "SeaOfProbabilitiesActor.h"
#include "SeaNoise.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Materials/MaterialParameterCollection.h"
#include "Kismet/KismetMaterialLibrary.h"
#include "Kismet/GameplayStatics.h"
#include "Engine/World.h"
#include "Engine/GameViewportClient.h"
#include "GameFramework/PlayerController.h"
#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "Async/ParallelFor.h"
#include "Engine/TextureRenderTarget2D.h"
#include "Engine/Texture2D.h"
#include "Kismet/KismetRenderingLibrary.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "RHI.h"

// three units <-> UE (spec section 2): UE = (-z, x, y) * 100
static FORCEINLINE FVector ThreeToUE(double X, double Y, double Z) { return FVector(-Z * 100.0, X * 100.0, Y * 100.0); }
static FORCEINLINE void UEToThree(const FVector& P, double& X, double& Y, double& Z) { X = P.Y / 100.0; Y = P.Z / 100.0; Z = -P.X / 100.0; }

// custom data layout shared with the materials
enum { CD_THETA = 0, CD_YOFF, CD_GLOW, CD_HUE, CD_X3, CD_Z3, CD_COUNT };

ASeaOfProbabilitiesActor::ASeaOfProbabilitiesActor()
{
	PrimaryActorTick.bCanEverTick = true;
	Dice = CreateDefaultSubobject<UInstancedStaticMeshComponent>(TEXT("Dice"));
	SetRootComponent(Dice);
	Dice->NumCustomDataFloats = CD_COUNT;
	Dice->SetCastShadow(true);
	Dice->SetMobility(EComponentMobility::Movable);
}

float ASeaOfProbabilitiesActor::Hash01(uint32 I, uint32 Salt)
{
	uint32 H = (I + 1u) * 2654435761u ^ (Salt * 0x9E3779B9u);
	H ^= H >> 13; H *= 0x5bd1e995u; H ^= H >> 15;
	return (H & 0xFFFFFFu) / 16777216.f;
}

void ASeaOfProbabilitiesActor::OnConstruction(const FTransform&)
{
	RebuildField();
}

bool ASeaOfProbabilitiesActor::EnsureState()
{
	const int32 N = Cols * Rows;
	const bool bOk = DieCount == N && Theta.Num() == N && Omega.Num() == N && YOffset.Num() == N
		&& YVel.Num() == N && Glow.Num() == N && Hue.Num() == N && X3.Num() == N && Z3.Num() == N
		&& Activated.Num() == N && Dice && Dice->GetInstanceCount() == N;
	if (!bOk) RebuildField();
	return DieCount > 0;
}

void ASeaOfProbabilitiesActor::BeginPlay()
{
	Super::BeginPlay();
	EnsureState();
	DefaultsJson = ExportSettingsJson();     // authored values = "reset defaults"
	if (!LoadSettings()) ApplyLookToWorld(); // LoadSettings applies when a save exists
	LastInput = NowSeconds();
	NextIdle = LastInput + IdleAfter;
	if (APlayerController* PC = GetWorld()->GetFirstPlayerController())
	{
		PC->bShowMouseCursor = true;
		PC->bEnableClickEvents = true;
		PC->bEnableMouseOverEvents = true;
	}
	EnsureStartCamera();
}

#if WITH_EDITOR
void ASeaOfProbabilitiesActor::PostEditChangeProperty(FPropertyChangedEvent& E)
{
	Super::PostEditChangeProperty(E);
	const FName N = E.GetPropertyName();
	static const TSet<FName> Rebuild = { TEXT("Cols"), TEXT("Rows"), TEXT("Spacing"), TEXT("bRedAce"),
		TEXT("DieMesh"), TEXT("BodyMaterial"), TEXT("PipsMaterial"), TEXT("AceMaterial") };
	if (Rebuild.Contains(N)) RebuildField(); else PushParametersToCollection();
}
#endif

// ------------------------------------------------------------------ field

void ASeaOfProbabilitiesActor::RebuildField()
{
	Cols = FMath::Clamp(Cols, 8, 1024); Rows = FMath::Clamp(Rows, 8, 1024);
	const int32 N = Cols * Rows;
	W = (Cols - 1) * (double)Spacing; D = (Rows - 1) * (double)Spacing;
	Theta.SetNumUninitialized(N); Omega.SetNumZeroed(N); YOffset.SetNumZeroed(N); YVel.SetNumZeroed(N);
	Glow.SetNumZeroed(N); Hue.SetNumUninitialized(N); X3.SetNumUninitialized(N); Z3.SetNumUninitialized(N);
	Activated.SetNumZeroed(N);
	StateCpu.SetNumZeroed(N);
	Splashes.Reset();

	Dice->ClearInstances();
	Dice->NumCustomDataFloats = CD_COUNT;
	if (DieMesh) Dice->SetStaticMesh(DieMesh);
	EnsureWaveResources();   // RT sized to the grid + MIDs bound to it (falls back to the raw materials)

	TArray<FTransform> Xf; Xf.Reserve(N);
	for (int32 I = 0; I < N; ++I)
	{
		const int32 Ix = I % Cols, Iz = I / Cols;
		const double X = -W / 2 + Ix * (double)Spacing, Z = -D / 2 + Iz * (double)Spacing;
		X3[I] = (float)X; Z3[I] = (float)Z;
		Theta[I] = FMath::FloorToInt(Hash01(I, 1) * 4.f) * HALF_PI;     // random quarter turn
		Hue[I] = Hash01(I, 2);
		Xf.Add(FTransform(FRotator::ZeroRotator, ThreeToUE(X, 0, Z)));  // height lives in the material
	}
	Dice->AddInstances(Xf, false);
	DieCount = N;
	PushParametersToCollection();
	PushAll();
}

void ASeaOfProbabilitiesActor::EnsureWaveResources()
{
	UMaterialInterface* Src[3] = { BodyMaterial, PipsMaterial, AceMaterial };
	if (!WaveMaterial)
	{
		for (int32 S = 0; S < 3; ++S) if (Src[S]) Dice->SetMaterial(S, Src[S]);
		return;
	}
	if (!WaveRT || WaveRT->SizeX != Cols || WaveRT->SizeY != Rows)
	{
		// M_Wave stores 1 + h/1024 (the UI-domain pixel shader clamps emissive at 0 and most
		// heights are negative); clear to the encoding of h = 0 so the frame before the first
		// draw does not sink the field.
		WaveRT = UKismetRenderingLibrary::CreateRenderTarget2D(this, Cols, Rows, RTF_R32f, FLinearColor(1.f, 0.f, 0.f, 0.f), false, false);
		if (WaveRT)
		{
			WaveRT->Filter = TF_Nearest;             // one texel per die, sampled at its centre
			WaveRT->AddressX = WaveRT->AddressY = TA_Clamp;
			WaveRT->UpdateResourceImmediate(false);
		}
		DieMIDs.Reset();
	}
	if (!StateTex || StateTex->GetSizeX() != Cols || StateTex->GetSizeY() != Rows)
	{
		StateTex = UTexture2D::CreateTransient(Cols, Rows, PF_A32B32G32R32F);
		if (StateTex)
		{
			StateTex->Filter = TF_Nearest;
			StateTex->AddressX = StateTex->AddressY = TA_Clamp;
			StateTex->SRGB = false;
			StateTex->NeverStream = true;
			StateTex->UpdateResource();
		}
		DieMIDs.Reset();
	}
	if (DieMIDs.Num() != 3)
	{
		DieMIDs.SetNum(3);
		for (int32 S = 0; S < 3; ++S)
		{
			DieMIDs[S] = Src[S] ? UMaterialInstanceDynamic::Create(Src[S], this) : nullptr;
			if (DieMIDs[S] && WaveRT) DieMIDs[S]->SetTextureParameterValue(TEXT("WaveRT"), WaveRT);
			if (DieMIDs[S] && StateTex) DieMIDs[S]->SetTextureParameterValue(TEXT("StateRT"), StateTex);
		}
	}
	for (int32 S = 0; S < 3; ++S) if (DieMIDs[S]) Dice->SetMaterial(S, DieMIDs[S]);
}

void ASeaOfProbabilitiesActor::PushAll()
{
	if (!Dice || Dice->GetInstanceCount() != DieCount) return;
	// static per-instance data, written once: the die's grid position (the dynamic
	// state travels through StateTex). [0..3] are kept for tools that read them.
	float Row[CD_COUNT];
	for (int32 I = 0; I < DieCount; ++I)
	{
		Row[CD_THETA] = Theta[I]; Row[CD_YOFF] = 0.f; Row[CD_GLOW] = 0.f;
		Row[CD_HUE] = Hue[I]; Row[CD_X3] = X3[I]; Row[CD_Z3] = Z3[I];
		Dice->SetCustomData(I, MakeArrayView(Row, CD_COUNT), false);
	}
	Dice->MarkRenderInstancesDirty();
	PushInstanceData();
}

void ASeaOfProbabilitiesActor::Scramble()
{
	if (!EnsureState()) return;
	for (int32 I = 0; I < DieCount; ++I) { Activated[I] = 0; Omega[I] += 5.f + Hash01(I, 7) * 6.f; }
}

void ASeaOfProbabilitiesActor::PushParametersToCollection()
{
	if (!Collection) return;
	UObject* Ctx = this;
	auto S = [&](const TCHAR* Name, float V) { UKismetMaterialLibrary::SetScalarParameterValue(Ctx, Collection, FName(Name), V); };
	auto V = [&](const TCHAR* Name, const FLinearColor& C) { UKismetMaterialLibrary::SetVectorParameterValue(Ctx, Collection, FName(Name), C); };
	S(TEXT("T"), (float)WaveT);
	S(TEXT("WaveAmp"), WaveAmp); S(TEXT("WaveScale"), WaveScale); S(TEXT("HorizonR"), HorizonR);
	S(TEXT("ZFront"), (float)(D / 2)); S(TEXT("GlowStrength"), GlowStrength); S(TEXT("Vignette"), Vignette);
	S(TEXT("Cols"), (float)Cols); S(TEXT("Rows"), (float)Rows); S(TEXT("Spacing"), Spacing);
	S(TEXT("W"), (float)W); S(TEXT("D"), (float)D);
	S(TEXT("FogNear"), FogNear); S(TEXT("FogFar"), FogFar); S(TEXT("RedAce"), bRedAce ? 1.f : 0.f);
	V(TEXT("GlowColorA"), GlowColorA); V(TEXT("GlowColorB"), GlowColorB);
	V(TEXT("DiceColor"), DiceColor); V(TEXT("BgColor"), BgColor);
}

// ------------------------------------------------------------------ height / picking

double ASeaOfProbabilitiesActor::HeightAt(double X, double Z) const
{
	const double F = WaveScale, T = WaveT, ZFront = D / 2;
	const double Wave = WaveAmp * (0.75 * SeaNoise::Noise2(X * F + T, Z * F + T * 0.35)
		+ 0.25 * SeaNoise::Noise2(X * F * 2.6 - T * 0.6, Z * F * 2.6));
	const double Dz = Z - ZFront;
	return Wave - (X * X + Dz * Dz) / HorizonR;
}

int32 ASeaOfProbabilitiesActor::CellAt(double X, double Z) const
{
	const int32 Ix = FMath::RoundToInt((X + W / 2) / Spacing), Iz = FMath::RoundToInt((Z + D / 2) / Spacing);
	if (Ix < 0 || Iz < 0 || Ix >= Cols || Iz >= Rows) return -1;
	const double Cx = -W / 2 + Ix * (double)Spacing, Cz = -D / 2 + Iz * (double)Spacing;
	if (FMath::Abs(X - Cx) > 0.55 * Spacing || FMath::Abs(Z - Cz) > 0.55 * Spacing) return -1;
	return Iz * Cols + Ix;
}

bool ASeaOfProbabilitiesActor::PickField(FVector2D& OutXZ) const
{
	APlayerController* PC = GetWorld() ? GetWorld()->GetFirstPlayerController() : nullptr;
	if (!PC) return false;
	float Mx, My;
	if (!PC->GetMousePosition(Mx, My)) return false;
	FVector O, Dir;
	if (!PC->DeprojectScreenPositionToWorld(Mx, My, O, Dir)) return false;
	double Ox, Oy, Oz, Dx, Dy, Dz;
	UEToThree(O, Ox, Oy, Oz);
	Dx = Dir.Y; Dy = Dir.Z; Dz = -Dir.X;
	// march the ray against the analytic surface, then bisect (spec 4.5)
	auto F = [&](double S) { return (Oy + Dy * S) - HeightAt(Ox + Dx * S, Oz + Dz * S); };
	double Prev = 0, PrevF = F(0);
	if (PrevF <= 0) return false;
	for (double S = 0.5; S <= 600.0; S += 0.5)
	{
		const double Fs = F(S);
		if (Fs <= 0)
		{
			double A = Prev, B = S;
			for (int32 K = 0; K < 24; ++K) { const double M = 0.5 * (A + B); if (F(M) > 0) A = M; else B = M; }
			const double S2 = 0.5 * (A + B);
			OutXZ = FVector2D(Ox + Dx * S2, Oz + Dz * S2);
			return true;
		}
		Prev = S; PrevF = Fs;
	}
	return false;
}

// ------------------------------------------------------------------ pulses / splashes

void ASeaOfProbabilitiesActor::Pulse(int32 J, float K)
{
	if (!EnsureState() || J < 0 || J >= DieCount) return;
	const int32 Jx = J % Cols, Jz = J / Cols;
	const int32 Cell = FMath::CeilToInt(PulseRadius / Spacing);
	for (int32 Dz = -Cell; Dz <= Cell; ++Dz)
	{
		const int32 Iz = Jz + Dz; if (Iz < 0 || Iz >= Rows) continue;
		for (int32 Dx = -Cell; Dx <= Cell; ++Dx)
		{
			const int32 Ix = Jx + Dx; if (Ix < 0 || Ix >= Cols) continue;
			const double Dist = Spacing * FMath::Sqrt((double)(Dx * Dx + Dz * Dz));
			if (Dist > PulseRadius) continue;
			const float Fall = (float)(1.0 - Dist / PulseRadius);
			const int32 Idx = Iz * Cols + Ix;
			Omega[Idx] += PulseStrength * Fall * Fall * K;
			if (Fall >= ActivateAt) Activated[Idx] = 1;
		}
	}
}

void ASeaOfProbabilitiesActor::Splash(double X, double Z, float K)
{
	FSeaSplash S; S.X = X; S.Z = Z; S.T0 = NowSeconds(); S.LastR = 0; S.K = K;
	Splashes.Add(S);
}

void ASeaOfProbabilitiesActor::AdvanceSplashes(double Now)
{
	for (int32 Si = Splashes.Num() - 1; Si >= 0; --Si)
	{
		FSeaSplash& S = Splashes[Si];
		const double R = (Now - S.T0) * RingSpeed;
		// only the grid rectangle the ring can touch this frame (radius <= splashRadius),
		// not all N dice - identical result, O(ring) instead of O(N) per splash
		const double Rm = FMath::Min(R, (double)SplashRadius);
		const int32 X0 = FMath::Max(0, FMath::FloorToInt((S.X - Rm + W / 2) / Spacing)), X1 = FMath::Min(Cols - 1, FMath::CeilToInt((S.X + Rm + W / 2) / Spacing));
		const int32 Z0 = FMath::Max(0, FMath::FloorToInt((S.Z - Rm + D / 2) / Spacing)), Z1 = FMath::Min(Rows - 1, FMath::CeilToInt((S.Z + Rm + D / 2) / Spacing));
		for (int32 Iz = Z0; Iz <= Z1; ++Iz)
		{
			for (int32 Ix = X0; Ix <= X1; ++Ix)
			{
				const int32 I = Iz * Cols + Ix;
				const double Dd = FMath::Sqrt(FMath::Square(X3[I] - S.X) + FMath::Square(Z3[I] - S.Z));
				if (Dd <= S.LastR || Dd > R || Dd > SplashRadius) continue;
				const float Fall = (float)(1.0 - Dd / SplashRadius);
				YVel[I] += SplashHeight * Fall * S.K;
				Omega[I] += SplashSpin * Fall * S.K;
				if (Fall >= ActivateAt) Activated[I] = 1;
			}
		}
		S.LastR = R;
		if (R > SplashRadius) Splashes.RemoveAt(Si);
	}
}

// ------------------------------------------------------------------ input / idle

void ASeaOfProbabilitiesActor::HandleInput(double Now)
{
	APlayerController* PC = GetWorld()->GetFirstPlayerController();
	if (!PC) return;
	float Mx, My;
	const bool bHaveMouse = PC->GetMousePosition(Mx, My);
	const FVector2D Mouse = bHaveMouse ? FVector2D(Mx, My) : FVector2D(-1, -1);
	const bool bDown = PC->IsInputKeyDown(EKeys::LeftMouseButton);
	const bool bAnyButton = bDown || PC->IsInputKeyDown(EKeys::RightMouseButton) || PC->IsInputKeyDown(EKeys::MiddleMouseButton);
	if (bHaveMouse && !Mouse.Equals(LastMouse, 0.01f)) LastInput = Now;
	if (bAnyButton || PC->IsInputKeyDown(EKeys::AnyKey) || !FMath::IsNearlyZero(PC->GetInputAnalogKeyState(EKeys::MouseWheelAxis))) LastInput = Now;
	LastMouse = Mouse;

	if (PC->WasInputKeyJustPressed(EKeys::SpaceBar)) bFrozen = !bFrozen;

	// hover -> pulse (skipped while any button is held or the cursor is outside)
	if (bHaveMouse && !bAnyButton)
	{
		FVector2D Hit;
		const int32 Cell = PickField(Hit) ? CellAt(Hit.X, Hit.Y) : -1;
		if (Cell != LastHoverCell) { LastHoverCell = Cell; if (Cell >= 0) Pulse(Cell, 1.f); }
	}
	// click = release within 6 px and 350 ms of the press (spec 4.5)
	if (bDown && !bMouseWasDown) { PressPos = Mouse; PressTime = Now; }
	if (!bDown && bMouseWasDown && bHaveMouse)
	{
		if (FVector2D::Distance(Mouse, PressPos) <= 6.0 && Now - PressTime <= 0.35)
		{
			FVector2D Hit;
			if (PickField(Hit)) Splash(Hit.X, Hit.Y, 1.f);
		}
	}
	bMouseWasDown = bDown;
}

void ASeaOfProbabilitiesActor::IdleLife(double Now)
{
	const bool bIsIdle = bIdle && (Now - LastInput >= IdleAfter);
	if (!bIsIdle) { LastIdleCell = -1; return; }
	if (Now >= NextIdle)
	{
		const double X = (FMath::FRand() - 0.5) * W * 0.7, Z = (FMath::FRand() - 0.5) * D * 0.7;
		Splash(X, Z, IdleStrength);
		NextIdle = Now + IdleEvery * (0.6 + FMath::FRand() * 0.8);
	}
	if (bIdleCursor)
	{
		const double Tt = Now * IdleCursorSpeed;
		const double X = SeaNoise::Noise2(Tt, 3.7) * W * 0.45, Z = SeaNoise::Noise2(Tt + 11.1, 9.2) * D * 0.45;
		const int32 Ix = FMath::Clamp(FMath::RoundToInt((X + W / 2) / Spacing), 0, Cols - 1);
		const int32 Iz = FMath::Clamp(FMath::RoundToInt((Z + D / 2) / Spacing), 0, Rows - 1);
		const int32 Cell = Iz * Cols + Ix;
		if (Cell != LastIdleCell) { LastIdleCell = Cell; Pulse(Cell, IdleCursorStrength); }
	}
}

// ------------------------------------------------------------------ integration (spec 4.7, no intro)

void ASeaOfProbabilitiesActor::Integrate(float Dt)
{
	// independent per die -> parallel (1M dice: ~27 ms serial). A die that has come to
	// rest is snapped exactly to rest so it stops changing - and stops being pushed.
	ParallelFor(DieCount, [&](int32 I)
	{
		float Rest;
		if (Activated[I]) { const float T0 = 0.f; Rest = T0 + FMath::RoundToFloat((Theta[I] - T0) / TWO_PI) * TWO_PI; }
		else Rest = FMath::RoundToFloat(Theta[I] / HALF_PI) * HALF_PI;
		Omega[I] += (-SpringK * (Theta[I] - Rest) - SpringC * Omega[I]) * Dt;
		Theta[I] += Omega[I] * Dt;
		if (FMath::Abs(Omega[I]) < 1e-3f && FMath::Abs(Theta[I] - Rest) < 1e-4f) { Theta[I] = Rest; Omega[I] = 0.f; }
		YVel[I] += (-14.f * YOffset[I] - 2.4f * YVel[I]) * Dt;
		YOffset[I] += YVel[I] * Dt;
		if (FMath::Abs(YOffset[I]) < 1e-4f && FMath::Abs(YVel[I]) < 1e-3f) { YOffset[I] = 0.f; YVel[I] = 0.f; }
		const float GTarget = FMath::Min(1.f, FMath::Abs(Omega[I]) * GlowSense);
		Glow[I] += (GTarget - Glow[I]) * FMath::Min(1.f, Dt * (GTarget > Glow[I] ? 10.f : GlowFade));
		if (Glow[I] < 2e-3f && GTarget < 2e-3f) Glow[I] = 0.f;
		StateCpu[I] = FLinearColor(Theta[I], YOffset[I], Glow[I], Hue[I]);
	});
}

void ASeaOfProbabilitiesActor::PushInstanceData()
{
	// Upload the whole state texture (theta, yOffset, glow, hue per die). 4 MB at 512x512:
	// a memcpy and a texture update, instead of touching the ISM instance buffer at all.
	if (!StateTex || StateCpu.Num() != DieCount || StateTex->GetSizeX() * StateTex->GetSizeY() != DieCount) return;
	const double T0 = FPlatformTime::Seconds();
	if (StateCpu.Num() == 0) { LastPushed = 0; return; }
	// keep hue for dice Integrate hasn't visited yet (first frame after a rebuild)
	if (StateCpu[0].A == 0.f && Hue.Num() == DieCount)
		for (int32 I = 0; I < DieCount; ++I) StateCpu[I] = FLinearColor(Theta[I], YOffset[I], Glow[I], Hue[I]);
	const int32 W2 = StateTex->GetSizeX(), H2 = StateTex->GetSizeY();
	const SIZE_T Bytes = (SIZE_T)DieCount * sizeof(FLinearColor);
	uint8* Copy = (uint8*)FMemory::Malloc(Bytes);
	FMemory::Memcpy(Copy, StateCpu.GetData(), Bytes);
	FUpdateTextureRegion2D* Region = new FUpdateTextureRegion2D(0, 0, 0, 0, W2, H2);
	StateTex->UpdateTextureRegions(0, 1, Region, W2 * sizeof(FLinearColor), sizeof(FLinearColor), Copy,
		[](uint8* Data, const FUpdateTextureRegion2D* R) { FMemory::Free(Data); delete R; });
	LastPushed = DieCount;
	MsPush = (FPlatformTime::Seconds() - T0) * 1000.0;
}

// ------------------------------------------------------------------ camera

void ASeaOfProbabilitiesActor::EnsureStartCamera()
{
	if (!bSpawnStartCamera || StartCamera.IsValid()) return;
	APlayerController* PC = GetWorld()->GetFirstPlayerController();
	if (!PC) return;
	// spec 5: three pos (-23.55, 27.5, 65.72) looking at (2.67, -22.52, 6.29)
	const FVector Pos = ThreeToUE(-23.55, 27.5, 65.72), Target = ThreeToUE(2.67, -22.52, 6.29);
	FActorSpawnParameters Sp; Sp.Owner = this;
	ACameraActor* Cam = GetWorld()->SpawnActor<ACameraActor>(Pos, (Target - Pos).Rotation(), Sp);
	if (!Cam) return;
	UCameraComponent* CC = Cam->GetCameraComponent();
	CC->SetConstraintAspectRatio(false);
	CC->ProjectionMode = ECameraProjectionMode::Perspective;
	StartCamera = Cam;
	PC->SetViewTargetWithBlend(Cam, 0.f);
}

// ------------------------------------------------------------------ tick (spec 4.4 order)

void ASeaOfProbabilitiesActor::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (!EnsureState()) return;
	const double Now = NowSeconds();
	const float Dt = FMath::Min(DeltaSeconds, 0.033f);
	if (!bFrozen) WaveT += Dt * WaveSpeed * (bReducedMotion ? 0.12f : 1.f);

	const bool bGame = GetWorld() && GetWorld()->IsGameWorld();
	if (bGame)
	{
		// BeginPlay runs before the controller possesses its pawn, and possession
		// resets the view target - so keep re-asserting the spec camera until it sticks.
		if (!StartCamera.IsValid()) EnsureStartCamera();
		if (APlayerController* PC = GetWorld()->GetFirstPlayerController())
		{
			if (StartCamera.IsValid() && PC->GetViewTarget() != StartCamera.Get())
				PC->SetViewTargetWithBlend(StartCamera.Get(), 0.f);
		}
		// UE's FOV is horizontal; keep the spec's 42 degrees VERTICAL whatever the aspect
		if (StartCamera.IsValid() && GEngine && GEngine->GameViewport)
		{
			FVector2D Vp; GEngine->GameViewport->GetViewportSize(Vp);
			if (Vp.Y > 0)
			{
				const float HFov = 2.f * FMath::RadiansToDegrees(FMath::Atan(FMath::Tan(FMath::DegreesToRadians(VerticalFov * 0.5f)) * (Vp.X / Vp.Y)));
				StartCamera->GetCameraComponent()->SetFieldOfView(HFov);
			}
		}
		HandleInput(Now);
		IdleLife(Now);
	}
	const double TSim = FPlatformTime::Seconds();
	AdvanceSplashes(Now);
	Integrate(Dt);
	MsSim = (FPlatformTime::Seconds() - TSim) * 1000.0;
	if (PushEveryNFrames <= 1 || (GFrameCounter % FMath::Max(1, PushEveryNFrames)) == 0) PushInstanceData();
	// wave: MPC time first, then redraw the per-die height texture (GPU, 1 texel per die)
	if (Collection) UKismetMaterialLibrary::SetScalarParameterValue(this, Collection, TEXT("T"), (float)WaveT);
	if (WaveRT && WaveMaterial)
	{
		const double TW = FPlatformTime::Seconds();
		UKismetRenderingLibrary::DrawMaterialToRenderTarget(this, WaveRT, WaveMaterial);
		MsHeight = (FPlatformTime::Seconds() - TW) * 1000.0;
	}
}
