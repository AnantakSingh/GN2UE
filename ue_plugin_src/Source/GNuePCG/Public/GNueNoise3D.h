// GNue Noise 3D — per-point 3D Perlin FBM, the stand-in for Blender's Noise
// Texture. Exists because UE 5.8's stock Spatial Noise node is strictly 2D
// (every mode samples X/Y only), which degenerates on vertical surfaces:
// whole columns of instances share one noise value, producing straight
// top-to-bottom stripes instead of organic patches.

#pragma once

#include "PCGSettings.h"
#include "Elements/PCGPointOperationElementBase.h"

#include "GNueNoise3D.generated.h"

UENUM(BlueprintType)
enum class EGNueNoiseOutput : uint8
{
	/** Write the mapped noise value into $Density (coverage masks). */
	Density       UMETA(DisplayName = "Density"),
	/** Multiply the selected scale components by the mapped noise value. */
	ScaleMultiply UMETA(DisplayName = "Scale Multiply"),
};

/**
 * 3D Perlin fractal noise evaluated at each point's world position.
 */
UCLASS(BlueprintType, ClassGroup = (Procedural))
class GNUEPCG_API UGNueNoise3DSettings : public UPCGSettings
{
	GENERATED_BODY()

public:
	//~Begin UPCGSettings interface
#if WITH_EDITOR
	virtual FName GetDefaultNodeName() const override { return FName(TEXT("GNueNoise3D")); }
	virtual FText GetDefaultNodeTitle() const override { return NSLOCTEXT("GNueNoise3D", "NodeTitle", "GNue Noise 3D"); }
	virtual FText GetNodeTooltipText() const override { return NSLOCTEXT("GNueNoise3D", "NodeTooltip", "3D Perlin FBM per point (Blender Noise Texture equivalent) - the stock Spatial Noise node is 2D-only and stripes on vertical surfaces."); }
	virtual EPCGSettingsType GetType() const override { return EPCGSettingsType::PointOps; }
#endif
	virtual bool UseSeed() const override { return true; }

protected:
	virtual TArray<FPCGPinProperties> InputPinProperties() const override { return Super::DefaultPointInputPinProperties(); }
	virtual TArray<FPCGPinProperties> OutputPinProperties() const override { return Super::DefaultPointOutputPinProperties(); }
	virtual FPCGElementPtr CreateElement() const override;
	//~End UPCGSettings interface

public:
	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	EGNueNoiseOutput Output = EGNueNoiseOutput::Density;

	/** Blender Noise Texture 'Scale': feature frequency per metre of world space. */
	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	double NoiseScale = 1.0;

	/** Blender Noise Texture 'Detail': number of FBM octaves (1-8). */
	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable, ClampMin = "1", ClampMax = "8"))
	int32 Detail = 3;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	int32 NoiseSeed = 0;

	/** Noise (0-1) is remapped to [OutMin, OutMax] before writing/multiplying. */
	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	double OutMin = 0.0;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	double OutMax = 1.0;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable, EditCondition = "Output == EGNueNoiseOutput::ScaleMultiply"))
	bool bScaleX = false;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable, EditCondition = "Output == EGNueNoiseOutput::ScaleMultiply"))
	bool bScaleY = false;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable, EditCondition = "Output == EGNueNoiseOutput::ScaleMultiply"))
	bool bScaleZ = true;
};

class FGNueNoise3DElement : public FPCGPointOperationElementBase
{
protected:
	virtual bool ExecuteInternal(FPCGContext* Context) const override;
	virtual EPCGPointNativeProperties GetPropertiesToAllocate(FPCGContext* InContext) const override;
	virtual bool ShouldCopyPoints() const override { return true; }
	virtual bool SupportsBasePointDataInputs(FPCGContext* InContext) const override { return true; }
};
