#include "SeaOfProbabilitiesActor.h"
#include "SeaNoise.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Materials/MaterialParameterCollection.h"
#include "Kismet/KismetMaterialLibrary.h"
#include "Engine/World.h"
#include "Engine/GameViewportClient.h"
#include "GameFramework/PlayerController.h"
#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"

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

void ASeaOfProbabilitiesActor::BeginPlay()
{
	Super::BeginPlay();
	if (DieCount == 0) RebuildField();
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
	Splashes.Reset();

	Dice->ClearInstances();
	Dice->NumCustomDataFloats = CD_COUNT;
	if (DieMesh) Dice->SetStaticMesh(DieMesh);
	if (BodyMaterial) Dice->SetMaterial(0, BodyMaterial);
	if (PipsMaterial) Dice->SetMaterial(1, PipsMaterial);
	if (AceMaterial) Dice->SetMaterial(2, AceMaterial);

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
	PushInstanceData();
	PushParametersToCollection();
}

void ASeaOfProbabilitiesActor::Scramble()
{
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
	if (J < 0 || J >= DieCount) return;
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
		for (int32 I = 0; I < DieCount; ++I)
		{
			const double Dd = FMath::Sqrt(FMath::Square(X3[I] - S.X) + FMath::Square(Z3[I] - S.Z));
			if (Dd <= S.LastR || Dd > R || Dd > SplashRadius) continue;
			const float Fall = (float)(1.0 - Dd / SplashRadius);
			YVel[I] += SplashHeight * Fall * S.K;
			Omega[I] += SplashSpin * Fall * S.K;
			if (Fall >= ActivateAt) Activated[I] = 1;
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
	for (int32 I = 0; I < DieCount; ++I)
	{
		float Rest;
		if (Activated[I]) { const float T0 = 0.f; Rest = T0 + FMath::RoundToFloat((Theta[I] - T0) / TWO_PI) * TWO_PI; }
		else Rest = FMath::RoundToFloat(Theta[I] / HALF_PI) * HALF_PI;
		Omega[I] += (-SpringK * (Theta[I] - Rest) - SpringC * Omega[I]) * Dt;
		Theta[I] += Omega[I] * Dt;
		YVel[I] += (-14.f * YOffset[I] - 2.4f * YVel[I]) * Dt;
		YOffset[I] += YVel[I] * Dt;
		const float GTarget = FMath::Min(1.f, FMath::Abs(Omega[I]) * GlowSense);
		Glow[I] += (GTarget - Glow[I]) * FMath::Min(1.f, Dt * (GTarget > Glow[I] ? 10.f : GlowFade));
	}
}

void ASeaOfProbabilitiesActor::PushInstanceData()
{
	if (!Dice || Dice->GetInstanceCount() != DieCount) return;
	for (int32 I = 0; I < DieCount; ++I)
	{
		Dice->SetCustomDataValue(I, CD_THETA, Theta[I], false);
		Dice->SetCustomDataValue(I, CD_YOFF, YOffset[I], false);
		Dice->SetCustomDataValue(I, CD_GLOW, Glow[I], false);
		Dice->SetCustomDataValue(I, CD_HUE, Hue[I], false);
		Dice->SetCustomDataValue(I, CD_X3, X3[I], false);
		Dice->SetCustomDataValue(I, CD_Z3, Z3[I], false);
	}
	Dice->MarkRenderStateDirty();
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
	if (DieCount == 0) return;
	const double Now = NowSeconds();
	const float Dt = FMath::Min(DeltaSeconds, 0.033f);
	if (!bFrozen) WaveT += Dt * WaveSpeed * (bReducedMotion ? 0.12f : 1.f);

	const bool bGame = GetWorld() && GetWorld()->IsGameWorld();
	if (bGame)
	{
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
	AdvanceSplashes(Now);
	Integrate(Dt);
	PushInstanceData();
	if (Collection) UKismetMaterialLibrary::SetScalarParameterValue(this, Collection, TEXT("T"), (float)WaveT);
}
