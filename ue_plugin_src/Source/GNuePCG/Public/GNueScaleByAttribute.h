// GNue Scale By Attribute — multiply (or set) each point's scale from a float
// attribute. Exists because UE 5.8's stock Attribute Maths Op (and the rest of
// the PCGMetadata* operation family) silently produces no output data, which
// makes the usual "multiply $Scale by an attribute" chain impossible to build
// from the shipped nodes. The GN→UE importer emits this node for Blender
// scale expressions whose factors are driven by proximity or noise.

#pragma once

#include "PCGSettings.h"
#include "Elements/PCGPointOperationElementBase.h"
#include "Metadata/PCGAttributePropertySelector.h"

#include "GNueScaleByAttribute.generated.h"

UENUM(BlueprintType)
enum class EGNueScaleOp : uint8
{
	/** Point scale is multiplied by the attribute value (Blender's scale factors). */
	Multiply UMETA(DisplayName = "Multiply"),
	/** Point scale is replaced by the attribute value. */
	Set      UMETA(DisplayName = "Set"),
};

/**
 * Multiplies or sets each point's scale using a per-point float attribute.
 */
UCLASS(BlueprintType, ClassGroup = (Procedural))
class GNUEPCG_API UGNueScaleByAttributeSettings : public UPCGSettings
{
	GENERATED_BODY()

public:
	//~Begin UPCGSettings interface
#if WITH_EDITOR
	virtual FName GetDefaultNodeName() const override { return FName(TEXT("GNueScaleByAttribute")); }
	virtual FText GetDefaultNodeTitle() const override { return NSLOCTEXT("GNueScaleByAttribute", "NodeTitle", "GNue Scale By Attribute"); }
	virtual FText GetNodeTooltipText() const override { return NSLOCTEXT("GNueScaleByAttribute", "NodeTooltip", "Multiplies (or sets) point scale from a float attribute — the per-point scale math the stock Attribute Maths Op cannot do."); }
	virtual EPCGSettingsType GetType() const override { return EPCGSettingsType::PointOps; }
#endif

protected:
	virtual TArray<FPCGPinProperties> InputPinProperties() const override { return Super::DefaultPointInputPinProperties(); }
	virtual TArray<FPCGPinProperties> OutputPinProperties() const override { return Super::DefaultPointOutputPinProperties(); }
	virtual FPCGElementPtr CreateElement() const override;
	//~End UPCGSettings interface

public:
	/** Float/double attribute (or point property) read per point. */
	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	FPCGAttributePropertyInputSelector ScaleSource;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	EGNueScaleOp Operation = EGNueScaleOp::Multiply;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	bool bScaleX = true;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	bool bScaleY = true;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	bool bScaleZ = true;

	/** Attribute value is clamped into this range before use. */
	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	double ValueMin = 0.0;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	double ValueMax = 1000000.0;
};

class FGNueScaleByAttributeElement : public FPCGPointOperationElementBase
{
protected:
	virtual bool ExecuteInternal(FPCGContext* Context) const override;
	virtual EPCGPointNativeProperties GetPropertiesToAllocate(FPCGContext* InContext) const override;
	virtual bool ShouldCopyPoints() const override { return true; }
	virtual bool SupportsBasePointDataInputs(FPCGContext* InContext) const override { return true; }
};
