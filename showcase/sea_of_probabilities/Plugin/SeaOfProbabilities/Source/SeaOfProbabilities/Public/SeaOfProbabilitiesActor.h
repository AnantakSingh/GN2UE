// Sea of Probabilities - the dice ocean. One actor owns the ISM field and runs
// the per-die simulation on the CPU (spec section 4), pushing theta / yOffset /
// glow / hue to the GPU as per-instance custom data; the die materials do the
// rotation, wave height and horizon curve in World Position Offset.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "SeaOfProbabilitiesActor.generated.h"

class UInstancedStaticMeshComponent;
class UMaterialParameterCollection;
class UMaterialInterface;
class UStaticMesh;
class ACameraActor;

USTRUCT()
struct FSeaSplash
{
	GENERATED_BODY()
	double X = 0, Z = 0, T0 = 0, LastR = 0;
	float K = 1.f;
};

UCLASS()
class SEAOFPROBABILITIES_API ASeaOfProbabilitiesActor : public AActor
{
	GENERATED_BODY()

public:
	ASeaOfProbabilitiesActor();

	// ---- field (rebuilds) ---------------------------------------------- spec 3
	UPROPERTY(EditAnywhere, Category = "Field", meta = (ClampMin = 8, ClampMax = 1024)) int32 Cols = 116;
	UPROPERTY(EditAnywhere, Category = "Field", meta = (ClampMin = 8, ClampMax = 1024)) int32 Rows = 100;
	UPROPERTY(EditAnywhere, Category = "Field") float Spacing = 1.2f;
	UPROPERTY(EditAnywhere, Category = "Field") bool bRedAce = false;

	// ---- waves
	UPROPERTY(EditAnywhere, Category = "Waves") float WaveSpeed = 0.11f;
	UPROPERTY(EditAnywhere, Category = "Waves") float WaveAmp = 7.f;
	UPROPERTY(EditAnywhere, Category = "Waves") float WaveScale = 0.018f;
	UPROPERTY(EditAnywhere, Category = "Waves") float HorizonR = 1010.f;
	UPROPERTY(EditAnywhere, Category = "Waves") bool bReducedMotion = false;

	// ---- ripple
	UPROPERTY(EditAnywhere, Category = "Ripple") float PulseRadius = 8.f;
	UPROPERTY(EditAnywhere, Category = "Ripple") float PulseStrength = 6.f;
	UPROPERTY(EditAnywhere, Category = "Ripple") float SpringK = 5.f;
	UPROPERTY(EditAnywhere, Category = "Ripple") float SpringC = 2.f;
	UPROPERTY(EditAnywhere, Category = "Ripple") float ActivateAt = 0.1f;

	// ---- splash (click)
	UPROPERTY(EditAnywhere, Category = "Splash") float SplashRadius = 44.f;
	UPROPERTY(EditAnywhere, Category = "Splash") float SplashHeight = 10.f;
	UPROPERTY(EditAnywhere, Category = "Splash") float SplashSpin = 20.f;
	UPROPERTY(EditAnywhere, Category = "Splash") float RingSpeed = 10.f;

	// ---- neon glow
	UPROPERTY(EditAnywhere, Category = "Glow") float GlowStrength = 4.f;
	UPROPERTY(EditAnywhere, Category = "Glow") float GlowSense = 0.03f;
	UPROPERTY(EditAnywhere, Category = "Glow") float GlowFade = 8.f;
	UPROPERTY(EditAnywhere, Category = "Glow") FLinearColor GlowColorA = FLinearColor(0.f, 0.2158f, 1.f);
	UPROPERTY(EditAnywhere, Category = "Glow") FLinearColor GlowColorB = FLinearColor(1.f, 0.f, 0.1329f);

	// ---- look
	UPROPERTY(EditAnywhere, Category = "Look") FLinearColor BgColor = FLinearColor(0.0176f, 0.0176f, 0.0176f);
	UPROPERTY(EditAnywhere, Category = "Look") FLinearColor DiceColor = FLinearColor::Black;
	UPROPERTY(EditAnywhere, Category = "Look") float FogNear = 24.f;
	UPROPERTY(EditAnywhere, Category = "Look") float FogFar = 95.f;
	UPROPERTY(EditAnywhere, Category = "Look") float Vignette = 0.45f;

	// ---- idle life
	UPROPERTY(EditAnywhere, Category = "Idle") bool bIdle = true;
	UPROPERTY(EditAnywhere, Category = "Idle") float IdleAfter = 4.f;
	UPROPERTY(EditAnywhere, Category = "Idle") float IdleEvery = 4.f;
	UPROPERTY(EditAnywhere, Category = "Idle") float IdleStrength = 0.6f;
	UPROPERTY(EditAnywhere, Category = "Idle") bool bIdleCursor = true;
	UPROPERTY(EditAnywhere, Category = "Idle") float IdleCursorSpeed = 0.12f;
	UPROPERTY(EditAnywhere, Category = "Idle") float IdleCursorStrength = 0.7f;

	// ---- camera: normally provided by ASeaCameraPawn (ASeaGameMode); this fallback
	// spawns a fixed camera only when the level runs under some other game mode
	UPROPERTY(EditAnywhere, Category = "Camera") bool bSpawnStartCamera = false;
	UPROPERTY(EditAnywhere, Category = "Camera") float VerticalFov = 42.f;

	// ---- assets
	UPROPERTY(EditAnywhere, Category = "Assets") TObjectPtr<UStaticMesh> DieMesh;
	UPROPERTY(EditAnywhere, Category = "Assets") TObjectPtr<UMaterialParameterCollection> Collection;
	UPROPERTY(EditAnywhere, Category = "Assets") TObjectPtr<UMaterialInterface> BodyMaterial;
	UPROPERTY(EditAnywhere, Category = "Assets") TObjectPtr<UMaterialInterface> PipsMaterial;
	UPROPERTY(EditAnywhere, Category = "Assets") TObjectPtr<UMaterialInterface> AceMaterial;

	UPROPERTY(VisibleAnywhere, Category = "Assets") TObjectPtr<UInstancedStaticMeshComponent> Dice;

	// ---- runtime state exposed for the HUD / readouts. Transient: the per-die
	// arrays below are not UPROPERTYs, so a serialized DieCount with empty arrays
	// (PIE duplicate / runtime load, where native OnConstruction does not rerun)
	// must never be trusted - see EnsureState().
	UPROPERTY(VisibleAnywhere, Transient, Category = "State") bool bFrozen = false;
	UPROPERTY(VisibleAnywhere, Transient, Category = "State") int32 DieCount = 0;

	UFUNCTION(BlueprintCallable, Category = "Sea") void RebuildField();
	UFUNCTION(BlueprintCallable, Category = "Sea") void Scramble();
	UFUNCTION(BlueprintCallable, Category = "Sea") void Splash(double X3, double Z3, float K);
	UFUNCTION(BlueprintCallable, Category = "Sea") void Pulse(int32 Cell, float K);
	UFUNCTION(BlueprintCallable, Category = "Sea") void ToggleFreeze() { bFrozen = !bFrozen; }
	UFUNCTION(BlueprintCallable, Category = "Sea") void PushParametersToCollection();

	/** Field height in three units at (x3, z3): wave + horizon curve (spec 4.2). */
	double HeightAt(double X3, double Z3) const;

	virtual void Tick(float DeltaSeconds) override;
	virtual bool ShouldTickIfViewportsOnly() const override { return true; }
	virtual void OnConstruction(const FTransform& Transform) override;
	virtual void BeginPlay() override;
#if WITH_EDITOR
	virtual void PostEditChangeProperty(FPropertyChangedEvent& E) override;
#endif

private:
	// per-die state (spec 4.1), index = iz * Cols + ix
	TArray<float> Theta, Omega, YOffset, YVel, Glow, Hue, X3, Z3;
	TArray<uint8> Activated;
	TArray<FSeaSplash> Splashes;
	double W = 0, D = 0;         // field extents in three units
	double WaveT = 0;            // wave time
	double LastInput = 0, NextIdle = 0;
	int32 LastHoverCell = -1, LastIdleCell = -1;
	bool bMouseWasDown = false;
	FVector2D PressPos = FVector2D::ZeroVector;
	double PressTime = 0;
	FVector2D LastMouse = FVector2D(-1, -1);
	TWeakObjectPtr<ACameraActor> StartCamera;

	static float Hash01(uint32 I, uint32 Salt);
	/** True when the per-die arrays match the ISM; rebuilds when they don't. */
	bool EnsureState();
	int32 CellAt(double X3, double Z3) const;      // nearest cell or -1 (0.55*spacing rule)
	bool PickField(FVector2D& OutXZ) const;         // mouse ray vs analytic height field
	void HandleInput(double Now);
	void IdleLife(double Now);
	void AdvanceSplashes(double Now);
	void Integrate(float Dt);
	void PushInstanceData();
	void EnsureStartCamera();
	static double NowSeconds() { return FPlatformTime::Seconds(); }
};
