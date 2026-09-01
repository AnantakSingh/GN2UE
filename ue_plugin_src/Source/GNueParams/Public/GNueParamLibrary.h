#pragma once

#include "Kismet/BlueprintFunctionLibrary.h"

#include "GNueParamLibrary.generated.h"

class UPCGGraph;

/**
 * Scripting bridge for the one PCG API Python cannot reach on UE 5.8:
 * declaring user parameters on a PCG graph. The GNue importer calls this after
 * building a graph so the Blender-side parameters appear on PCG volumes'
 * Details panels (values are then readable via PCGGraphParametersHelpers).
 */
UCLASS()
class GNUEPARAMS_API UGNueParamLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/**
	 * Declare graph parameters from a JSON spec:
	 *   [{"name": "Bridge_Width", "type": "float", "default": 1.15}, ...]
	 * Names should be sanitized identifiers (callers replace spaces with '_').
	 * Supported types: float, int, bool, vector. Parameters that already exist
	 * are left untouched (user-edited defaults survive reimports) unless
	 * bResetExisting is true, which rewrites their values to the spec defaults.
	 * Returns the number of parameters declared/reset, or -1 on bad input.
	 */
	UFUNCTION(BlueprintCallable, Category = "GNue")
	static int32 DeclareParameters(UPCGGraph* Graph, const FString& JsonSpec,
		bool bResetExisting = false);
};
