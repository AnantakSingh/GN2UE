using UnrealBuildTool;

public class GNuePCG : ModuleRules
{
	public GNuePCG(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core",
			"CoreUObject",
			"Engine",
			"PCG",
			"AssetRegistry",
		});
	}
}
