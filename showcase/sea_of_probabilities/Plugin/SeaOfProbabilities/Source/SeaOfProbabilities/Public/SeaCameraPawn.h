// The viewer. A pawn that IS the camera (no mesh, no gravity, no collision):
// three.js OrbitControls semantics from spec section 5 - left-drag orbits the
// target, right-drag pans, wheel dollies, damping 0.08, polar angle kept above
// the horizon, distance 10..260 three-units, vertical FOV 42 degrees. Also hosts
// the console commands used to exercise the simulation ("Sea*").
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/GameModeBase.h"
#include "SeaCameraPawn.generated.h"

class UCameraComponent;
class ASeaOfProbabilitiesActor;

UCLASS()
class SEAOFPROBABILITIES_API ASeaCameraPawn : public APawn
{
	GENERATED_BODY()

public:
	ASeaCameraPawn();

	// spec 5 (three units; converted on use): start pose, limits, feel
	UPROPERTY(EditAnywhere, Category = "Camera") FVector StartPosition3 = FVector(-23.55, 27.5, 65.72);
	UPROPERTY(EditAnywhere, Category = "Camera") FVector StartTarget3 = FVector(2.67, -22.52, 6.29);
	UPROPERTY(EditAnywhere, Category = "Camera") float VerticalFov = 42.f;
	UPROPERTY(EditAnywhere, Category = "Camera") float DampingFactor = 0.08f;
	UPROPERTY(EditAnywhere, Category = "Camera") float MinDistance3 = 10.f;
	UPROPERTY(EditAnywhere, Category = "Camera") float MaxDistance3 = 260.f;
	UPROPERTY(EditAnywhere, Category = "Camera") float MinElevationDeg = FMath::RadiansToDegrees(0.03f);   // polar <= pi/2 - 0.03
	UPROPERTY(EditAnywhere, Category = "Camera") bool bLockCamera = false;

	UPROPERTY(VisibleAnywhere, Category = "Camera") TObjectPtr<UCameraComponent> Camera;

	/** Camera pose in three units, as the web build's "copy camera" JSON. */
	UFUNCTION(BlueprintCallable, Category = "Sea") FString CameraJson() const;
	UFUNCTION(BlueprintCallable, Category = "Sea") void SetCamera3(FVector Position3, FVector Target3);

	// ---- console commands (Exec): usable from the editor console during PIE
	UFUNCTION(Exec) void SeaSplash(float X3, float Z3, float K = 1.f);
	UFUNCTION(Exec) void SeaPulse(int32 Cell, float K = 1.f);
	UFUNCTION(Exec) void SeaScramble();
	UFUNCTION(Exec) void SeaFreeze();
	UFUNCTION(Exec) void SeaCam();
	UFUNCTION(Exec) void SeaSetCam(float Px, float Py, float Pz, float Tx, float Ty, float Tz);
	UFUNCTION(Exec) void SeaStats();
	UFUNCTION(Exec) void SeaPushEvery(int32 N);     // profiling: instance-data push cadence
	// settings (spec 3 / 8): JSON round-trip with the web build, SaveGame, reset
	UFUNCTION(Exec) void SeaJson();                                   // log current settings JSON
	UFUNCTION(Exec) void SeaSet(const FString& Key, const FString& Value);   // one param by web key
	UFUNCTION(Exec) void SeaSave();
	UFUNCTION(Exec) void SeaLoad();
	UFUNCTION(Exec) void SeaReset();
	UFUNCTION(Exec) void SeaWriteJson(const FString& Path);           // "copy settings" to a file
	UFUNCTION(Exec) void SeaReadJson(const FString& Path);            // paste settings from a file

	virtual void Tick(float DeltaSeconds) override;
	virtual void BeginPlay() override;

private:
	// orbit state (UE cm / degrees)
	FVector Target = FVector::ZeroVector;
	double Distance = 8200.0;
	double Yaw = 0.0, Elevation = 0.0;             // elevation: 0 = horizon, 90 = straight above
	double YawDelta = 0.0, ElevDelta = 0.0, DollyScale = 1.0;
	FVector PanDelta = FVector::ZeroVector;
	FVector2D LastMouse = FVector2D(-1, -1);
	bool bDragging = false, bWasButtonDown = false;
	float FpsAvg = 0.f;

	ASeaOfProbabilitiesActor* Sea() const;
	void ApplyPose();
	void ReadInput(float DeltaSeconds);
};

/** Minimal game mode: the camera pawn and nothing else. */
UCLASS()
class SEAOFPROBABILITIES_API ASeaGameMode : public AGameModeBase
{
	GENERATED_BODY()
public:
	ASeaGameMode();
};
