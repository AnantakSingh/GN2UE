#include "Modules/ModuleManager.h"
#include "SeaNoise.h"

DEFINE_LOG_CATEGORY_STATIC(LogSea, Display, All);

class FSeaOfProbabilitiesModule : public IModuleInterface
{
public:
	virtual void StartupModule() override
	{
		// Acceptance check (spec section 10): the C++ noise must match the JS
		// function to 1e-6. Expected values were produced by running the web
		// version's noise2 under Node (showcase/.../noise/simplex2_ref.js).
		static const double Samples[][3] = {
			{0.3, 0.7, 0.895424056238}, {0.0, 0.0, 0.0}, {1.5, -2.25, 0.449113572331},
			{12.345, 67.89, -0.674422751634}, {-3.3, 3.3, -0.087150262211},
			{100.1, 0.02, -0.186303195566}, {5.72, 1.21, -0.257222621904}, {-0.5, 0.5, 0.249472338539},
		};
		double MaxDiff = 0.0;
		for (const auto& S : Samples)
		{
			MaxDiff = FMath::Max(MaxDiff, FMath::Abs(SeaNoise::Noise2(S[0], S[1]) - S[2]));
		}
		UE_LOG(LogSea, Display, TEXT("SEA NOISE CHECK: %s (max |C++ - JS| = %.3e over 8 samples)"),
			MaxDiff <= 1e-6 ? TEXT("PASS") : TEXT("FAIL"), MaxDiff);
	}
};

IMPLEMENT_MODULE(FSeaOfProbabilitiesModule, SeaOfProbabilities)
