// Sea of Probabilities - the dice ocean. One actor owns the ISM field and runs
// the per-die simulation on the CPU (spec section 4), pushing theta / yOffset /
// glow / hue to the GPU as per-instance custom data; the die materials do the
// rotation, wave height and horizon curve in World Position Offset.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "GameFramework/SaveGame.h"
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

/** Persisted settings: the web version's localStorage key, verbatim. */
UCLASS()
class SEAOFPROBABILITIES_API USeaSaveGame : public USaveGame
{
	GENERATED_BODY()
public:
	UPROPERTY() FString Json;
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

	// ---- lighting / post (spec 3, 6.3) - applied to the level's Sun / Sky / PostFX by ApplyLookToWorld()
	UPROPERTY(EditAnywhere, Category = "Lighting") float SunIntensity = 4.f;
	UPROPERTY(EditAnywhere, Category = "Lighting") FLinearColor SunColor = FLinearColor::White;
	UPROPERTY(EditAnywhere, Category = "Lighting") float SunAzimuth = 197.f;
	UPROPERTY(EditAnywhere, Category = "Lighting") float SunElevation = 34.f;
	UPROPERTY(EditAnywhere, Category = "Lighting") float HemiIntensity = 2.f;
	UPROPERTY(EditAnywhere, Category = "Lighting") float EnvIntensity = 2.f;
	UPROPERTY(EditAnywhere, Category = "Lighting") float Exposure = 0.52f;     // three toneMappingExposure
	UPROPERTY(EditAnywhere, Category = "Lighting") bool bShadows = true;
	UPROPERTY(EditAnywhere, Category = "Post FX") bool bPostFx = true;
	UPROPERTY(EditAnywhere, Category = "Post FX") bool bBloom = true;
	UPROPERTY(EditAnywhere, Category = "Post FX") float BloomStrength = 0.6f;
	UPROPERTY(EditAnywhere, Category = "Post FX") float BloomThreshold = 1.f;
	UPROPERTY(EditAnywhere, Category = "Post FX") float BloomRadius = 0.4f;
	// material constants (exported for round-trip; baked into the materials for now)
	UPROPERTY(EditAnywhere, Category = "Dice Material") float Roughness = 0.71f;
	UPROPERTY(EditAnywhere, Category = "Dice Material") float Metalness = 1.f;
	UPROPERTY(EditAnywhere, Category = "Dice Material") float Clearcoat = 0.09f;
	UPROPERTY(EditAnywhere, Category = "Dice Material") float ClearcoatRough = 0.29f;
	UPROPERTY(EditAnywhere, Category = "Dice Material") float Bevel = 0.18f;

	/** Exposure bias that reproduced three's 0.52 on the reference setup (see sea_level.py). */
	UPROPERTY(EditAnywhere, Category = "Lighting", AdvancedDisplay) float ExposureBiasAt052 = 10.2f;

	// ---- settings round-trip (spec 3): exact web key names; unknown keys are preserved
	UFUNCTION(BlueprintCallable, Category = "Sea") FString ExportSettingsJson() const;
	UFUNCTION(BlueprintCallable, Category = "Sea") bool ImportSettingsJson(const FString& Json, bool bApply = true);
	UFUNCTION(BlueprintCallable, Category = "Sea") bool SaveSettings();       // SaveGame slot "dice-ocean-params-v2"
	UFUNCTION(BlueprintCallable, Category = "Sea") bool LoadSettings();
	UFUNCTION(BlueprintCallable, Category = "Sea") void ResetDefaults();
	UFUNCTION(BlueprintCallable, Category = "Sea") void ApplyLookToWorld();
	/** Set one parameter by its web key ("waveAmp", "glowColorA", "cols", ...). */
	UFUNCTION(BlueprintCallable, Category = "Sea") bool SetParam(const FString& Key, const FString& Value);

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
	/** UI-domain material that writes wave+horizon height per die into WaveRT (M_Wave). */
	UPROPERTY(EditAnywhere, Category = "Assets") TObjectPtr<UMaterialInterface> WaveMaterial;

	UPROPERTY(VisibleAnywhere, Category = "Assets") TObjectPtr<UInstancedStaticMeshComponent> Dice;
	/** Cols x Rows R32F: height per die, redrawn every frame on the GPU; dice sample it in WPO. */
	UPROPERTY(VisibleAnywhere, Transient, Category = "Assets") TObjectPtr<class UTextureRenderTarget2D> WaveRT;
	/** Cols x Rows RGBA32F: (theta, yOffset, glow, hue) per die, uploaded from the CPU every
	 *  frame. Keeping dynamic state out of the ISM instance buffer is what makes 512x512 cheap:
	 *  any dirty instance makes UE re-upload the WHOLE instance buffer (~58 ms at 262k). */
	UPROPERTY(VisibleAnywhere, Transient, Category = "Assets") TObjectPtr<class UTexture2D> StateTex;
	UPROPERTY(Transient) TArray<TObjectPtr<class UMaterialInstanceDynamic>> DieMIDs;

	// ---- runtime state exposed for the HUD / readouts. Transient: the per-die
	// arrays below are not UPROPERTYs, so a serialized DieCount with empty arrays
	// (PIE duplicate / runtime load, where native OnConstruction does not rerun)
	// must never be trusted - see EnsureState().
	UPROPERTY(VisibleAnywhere, Transient, Category = "State") bool bFrozen = false;
	UPROPERTY(VisibleAnywhere, Transient, Category = "State") int32 DieCount = 0;
	/** Debug: push instance data only every N frames (1 = every frame). Isolates the
	 *  engine's per-instance update cost from everything else when profiling. */
	UPROPERTY(EditAnywhere, Transient, Category = "State") int32 PushEveryNFrames = 1;
	// per-frame cost breakdown (ms), read by SeaStats
	UPROPERTY(VisibleAnywhere, Transient, Category = "State") double MsSim = 0;     // splashes + integration
	UPROPERTY(VisibleAnywhere, Transient, Category = "State") double MsHeight = 0;  // wave RT draw (game-thread side)
	UPROPERTY(VisibleAnywhere, Transient, Category = "State") double MsPush = 0;    // instance-data push
	UPROPERTY(VisibleAnywhere, Transient, Category = "State") int32 LastPushed = 0; // state texels uploaded last frame

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
	TArray<FLinearColor> StateCpu;                     // staging for StateTex (theta, yOff, glow, hue)
	TArray<uint8> Activated;
	void PushAll();                                    // rebuild: static instance data once
	void EnsureWaveResources();                        // RT + state texture + MIDs for the current grid
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
	FString DefaultsJson;                       // snapshot at BeginPlay, for ResetDefaults
	TSharedPtr<class FJsonObject> Passthrough;  // keys we don't own (sound, intro...) from the last import
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
