#include "GNueScaleByAttribute.h"

#include "PCGContext.h"
#include "PCGPin.h"
#include "Data/PCGBasePointData.h"
#include "Metadata/Accessors/IPCGAttributeAccessor.h"
#include "Metadata/Accessors/PCGAttributeAccessorHelpers.h"

#include UE_INLINE_GENERATED_CPP_BY_NAME(GNueScaleByAttribute)

#define LOCTEXT_NAMESPACE "GNueScaleByAttributeElement"

FPCGElementPtr UGNueScaleByAttributeSettings::CreateElement() const
{
	return MakeShared<FGNueScaleByAttributeElement>();
}

EPCGPointNativeProperties FGNueScaleByAttributeElement::GetPropertiesToAllocate(FPCGContext* Context) const
{
	return EPCGPointNativeProperties::Transform;
}

bool FGNueScaleByAttributeElement::ExecuteInternal(FPCGContext* Context) const
{
	TRACE_CPUPROFILER_EVENT_SCOPE(FGNueScaleByAttributeElement::Execute);
	check(Context);

	const UGNueScaleByAttributeSettings* Settings = Context->GetInputSettings<UGNueScaleByAttributeSettings>();
	check(Settings);

	FGNueScaleByAttributeElement::ContextType* ScaleContext =
		static_cast<FGNueScaleByAttributeElement::ContextType*>(Context);

	const bool bMultiply = (Settings->Operation == EGNueScaleOp::Multiply);
	const bool bX = Settings->bScaleX;
	const bool bY = Settings->bScaleY;
	const bool bZ = Settings->bScaleZ;
	const double ValueMin = FMath::Min(Settings->ValueMin, Settings->ValueMax);
	const double ValueMax = FMath::Max(Settings->ValueMin, Settings->ValueMax);
	const FPCGAttributePropertyInputSelector SourceSelector = Settings->ScaleSource;

	return ExecutePointOperation(ScaleContext,
		[bMultiply, bX, bY, bZ, ValueMin, ValueMax, SourceSelector, Context]
		(const UPCGBasePointData* InputData, UPCGBasePointData* OutputData, int32 StartIndex, int32 Count)
	{
		const FPCGAttributePropertyInputSelector Selector = SourceSelector.CopyAndFixLast(InputData);

		const TUniquePtr<const IPCGAttributeAccessor> Accessor =
			PCGAttributeAccessorHelpers::CreateConstAccessor(InputData, Selector);
		const TUniquePtr<const IPCGAttributeAccessorKeys> Keys =
			PCGAttributeAccessorHelpers::CreateConstKeys(InputData, Selector);

		if (!Accessor.IsValid() || !Keys.IsValid())
		{
			PCGLog::Metadata::LogFailToCreateAccessorError(Selector, Context);
			return false;
		}

		TArray<double> Values;
		Values.SetNumUninitialized(Count);

		if (!Accessor->GetRange<double>(TArrayView<double>(Values.GetData(), Count), StartIndex, *Keys,
			EPCGAttributeAccessorFlags::AllowBroadcastAndConstructible))
		{
			PCGLog::Metadata::LogFailToGetAttributeError(Selector, Context);
			return false;
		}

		TPCGValueRange<FTransform> TransformRange = OutputData->GetTransformValueRange();

		for (int32 Index = StartIndex; Index < (StartIndex + Count); ++Index)
		{
			const double Value = FMath::Clamp(Values[Index - StartIndex], ValueMin, ValueMax);

			FTransform& Transform = TransformRange[Index];
			FVector Scale = Transform.GetScale3D();

			if (bX) { Scale.X = bMultiply ? Scale.X * Value : Value; }
			if (bY) { Scale.Y = bMultiply ? Scale.Y * Value : Value; }
			if (bZ) { Scale.Z = bMultiply ? Scale.Z * Value : Value; }

			Transform.SetScale3D(Scale);
		}

		return true;
	});
}

#undef LOCTEXT_NAMESPACE
