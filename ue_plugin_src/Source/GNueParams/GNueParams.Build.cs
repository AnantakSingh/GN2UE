using UnrealBuildTool;

public class GNueParams : ModuleRules
{
	public GNueParams(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core",
			"CoreUObject",
			"Engine",
			"PCG",
			"Json",
		});
	}
}
