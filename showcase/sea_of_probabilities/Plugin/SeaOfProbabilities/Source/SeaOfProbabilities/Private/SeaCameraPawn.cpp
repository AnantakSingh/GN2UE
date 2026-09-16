#include "SeaCameraPawn.h"
#include "SeaOfProbabilitiesActor.h"
#include "Camera/CameraComponent.h"
#include "Components/SceneComponent.h"
#include "Engine/World.h"
#include "Engine/GameViewportClient.h"
#include "EngineUtils.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/SpectatorPawn.h"

DEFINE_LOG_CATEGORY_STATIC(LogSeaCam, Display, All);

static FORCEINLINE FVector T2U(const FVector& T) { return FVector(-T.Z * 100.0, T.X * 100.0, T.Y * 100.0); }
static FORCEINLINE FVector U2T(const FVector& U) { return FVector(U.Y / 100.0, U.Z / 100.0, -U.X / 100.0); }

ASeaCameraPawn::ASeaCameraPawn()
{
	PrimaryActorTick.bCanEverTick = true;
	SetRootComponent(CreateDefaultSubobject<USceneComponent>(TEXT("Root")));
	Camera = CreateDefaultSubobject<UCameraComponent>(TEXT("Camera"));
	Camera->SetupAttachment(GetRootComponent());
	Camera->SetConstraintAspectRatio(false);
	bUseControllerRotationPitch = bUseControllerRotationYaw = bUseControllerRotationRoll = false;
	AutoPossessPlayer = EAutoReceiveInput::Disabled;
}

ASeaGameMode::ASeaGameMode()
{
	DefaultPawnClass = ASeaCameraPawn::StaticClass();
}

ASeaOfProbabilitiesActor* ASeaCameraPawn::Sea() const
{
	for (TActorIterator<ASeaOfProbabilitiesActor> It(GetWorld()); It; ++It) return *It;
	return nullptr;
}

void ASeaCameraPawn::BeginPlay()
{
	Super::BeginPlay();
	SetCamera3(StartPosition3, StartTarget3);
	if (APlayerController* PC = Cast<APlayerController>(GetController()))
	{
		PC->bShowMouseCursor = true;
		PC->bEnableClickEvents = true;
		PC->bEnableMouseOverEvents = true;
		PC->SetViewTargetWithBlend(this, 0.f);
	}
}

void ASeaCameraPawn::SetCamera3(FVector Position3, FVector Target3)
{
	Target = T2U(Target3);
	const FVector Pos = T2U(Position3);
	const FVector D = Pos - Target;
	Distance = D.Size();
	Yaw = FMath::RadiansToDegrees(FMath::Atan2(D.Y, D.X));
	Elevation = FMath::RadiansToDegrees(FMath::Atan2(D.Z, FMath::Sqrt(D.X * D.X + D.Y * D.Y)));
	YawDelta = ElevDelta = 0.0; DollyScale = 1.0; PanDelta = FVector::ZeroVector;
	ApplyPose();
}

void ASeaCameraPawn::ApplyPose()
{
	Elevation = FMath::Clamp(Elevation, (double)MinElevationDeg, 89.9);
	Distance = FMath::Clamp(Distance, MinDistance3 * 100.0, MaxDistance3 * 100.0);
	const double Cy = FMath::Cos(FMath::DegreesToRadians(Yaw)), Sy = FMath::Sin(FMath::DegreesToRadians(Yaw));
	const double Ce = FMath::Cos(FMath::DegreesToRadians(Elevation)), Se = FMath::Sin(FMath::DegreesToRadians(Elevation));
	const FVector Pos = Target + FVector(Ce * Cy, Ce * Sy, Se) * Distance;
	SetActorLocationAndRotation(Pos, (Target - Pos).Rotation());
}

void ASeaCameraPawn::ReadInput(float)
{
	APlayerController* PC = Cast<APlayerController>(GetController());
	if (!PC) return;
	float Mx, My;
	const bool bHaveMouse = PC->GetMousePosition(Mx, My);
	const FVector2D Mouse = bHaveMouse ? FVector2D(Mx, My) : FVector2D(-1, -1);
	FVector2D Vp(1920, 1080);
	if (GEngine && GEngine->GameViewport) GEngine->GameViewport->GetViewportSize(Vp);
	if (bHaveMouse && LastMouse.X >= 0 && !bLockCamera)
	{
		const FVector2D Delta = Mouse - LastMouse;
		if (PC->IsInputKeyDown(EKeys::LeftMouseButton))
		{
			// OrbitControls: a drag of the full viewport height = 2*pi (rotateSpeed 1)
			YawDelta -= 360.0 * Delta.X / Vp.Y;
			ElevDelta += 360.0 * Delta.Y / Vp.Y;
		}
		else if (PC->IsInputKeyDown(EKeys::RightMouseButton))
		{
			// pan: move the target in the camera plane; perspective pan scale (panSpeed 1)
			const double TargetDist = Distance * FMath::Tan(FMath::DegreesToRadians(VerticalFov * 0.5)) * 2.0 / Vp.Y;
			const FRotator R = GetActorRotation();
			PanDelta += (-FRotationMatrix(R).GetUnitAxis(EAxis::Y) * Delta.X + FRotationMatrix(R).GetUnitAxis(EAxis::Z) * Delta.Y) * TargetDist;
		}
	}
	if (!bLockCamera)
	{
		const float Wheel = PC->GetInputAnalogKeyState(EKeys::MouseWheelAxis);
		if (Wheel > 0) DollyScale *= 0.95;          // dollyIn  (zoomSpeed 1)
		else if (Wheel < 0) DollyScale /= 0.95;     // dollyOut
	}
	LastMouse = Mouse;
}

void ASeaCameraPawn::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	ReadInput(DeltaSeconds);
	// damping exactly like OrbitControls: apply a fraction, decay the rest
	Yaw += YawDelta * DampingFactor;       YawDelta *= (1.0 - DampingFactor);
	Elevation += ElevDelta * DampingFactor; ElevDelta *= (1.0 - DampingFactor);
	Target += PanDelta * DampingFactor;    PanDelta *= (1.0 - DampingFactor);
	if (!FMath::IsNearlyEqual(DollyScale, 1.0)) { Distance *= DollyScale; DollyScale = 1.0; }
	ApplyPose();
	// UE's FOV is horizontal: keep the spec's vertical 42 degrees at any aspect
	if (GEngine && GEngine->GameViewport)
	{
		FVector2D Vp; GEngine->GameViewport->GetViewportSize(Vp);
		if (Vp.Y > 0)
			Camera->SetFieldOfView(2.f * FMath::RadiansToDegrees(FMath::Atan(FMath::Tan(FMath::DegreesToRadians(VerticalFov * 0.5f)) * (Vp.X / Vp.Y))));
	}
}

FString ASeaCameraPawn::CameraJson() const
{
	const FVector P = U2T(GetActorLocation()), T = U2T(Target);
	return FString::Printf(TEXT("{\"position\":[%.2f,%.2f,%.2f],\"target\":[%.2f,%.2f,%.2f],\"fov\":%.0f}"),
		P.X, P.Y, P.Z, T.X, T.Y, T.Z, VerticalFov);
}

// ---- console commands ------------------------------------------------------

void ASeaCameraPawn::SeaSplash(float X3, float Z3, float K)
{
	if (ASeaOfProbabilitiesActor* S = Sea()) { S->Splash(X3, Z3, K); UE_LOG(LogSeaCam, Display, TEXT("SeaSplash(%g, %g, %g) -> splashes=%d"), X3, Z3, K, 1); }
}

void ASeaCameraPawn::SeaPulse(int32 Cell, float K)
{
	if (ASeaOfProbabilitiesActor* S = Sea()) { S->Pulse(Cell, K); UE_LOG(LogSeaCam, Display, TEXT("SeaPulse(%d, %g)"), Cell, K); }
}

void ASeaCameraPawn::SeaScramble()
{
	if (ASeaOfProbabilitiesActor* S = Sea()) { S->Scramble(); UE_LOG(LogSeaCam, Display, TEXT("SeaScramble")); }
}

void ASeaCameraPawn::SeaFreeze()
{
	if (ASeaOfProbabilitiesActor* S = Sea()) { S->ToggleFreeze(); UE_LOG(LogSeaCam, Display, TEXT("SeaFreeze -> frozen=%d"), S->bFrozen ? 1 : 0); }
}

void ASeaCameraPawn::SeaCam()
{
	UE_LOG(LogSeaCam, Display, TEXT("SeaCam %s"), *CameraJson());
}

void ASeaCameraPawn::SeaSetCam(float Px, float Py, float Pz, float Tx, float Ty, float Tz)
{
	SetCamera3(FVector(Px, Py, Pz), FVector(Tx, Ty, Tz));
	SeaCam();
}

void ASeaCameraPawn::SeaStats()
{
	ASeaOfProbabilitiesActor* S = Sea();
	const float Fps = 1.f / FMath::Max(GetWorld()->GetDeltaSeconds(), 1e-4f);
	UE_LOG(LogSeaCam, Display, TEXT("SeaStats dice=%d cols=%d rows=%d frozen=%d fps=%.1f cam=%s"),
		S ? S->DieCount : -1, S ? S->Cols : 0, S ? S->Rows : 0, S ? (int32)S->bFrozen : -1, Fps, *CameraJson());
}
