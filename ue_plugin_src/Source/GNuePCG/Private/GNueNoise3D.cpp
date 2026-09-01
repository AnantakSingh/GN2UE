#include "GNueNoise3D.h"

#include "PCGContext.h"
#include "PCGPin.h"
#include "Data/PCGBasePointData.h"

#include UE_INLINE_GENERATED_CPP_BY_NAME(GNueNoise3D)

#define LOCTEXT_NAMESPACE "GNueNoise3DElement"

namespace GNueNoise
{
	// Deterministic integer hash (PCG-family), seeded — no permutation table.
	FORCEINLINE uint32 Hash(int32 X, int32 Y, int32 Z, uint32 Seed)
	{
		uint32 H = Seed;
		H ^= static_cast<uint32>(X) * 0x8DA6B343u;
		H ^= static_cast<uint32>(Y) * 0xD8163841u;
		H ^= static_cast<uint32>(Z) * 0xCB1AB31Fu;
		H = (H ^ (H >> 13)) * 0x9E3779B1u;
		return H ^ (H >> 16);
	}

	// Gradient from one of 12 edge directions (classic Perlin).
	FORCEINLINE double Grad(uint32 H, double X, double Y, double Z)
	{
		switch (H % 12u)
		{
		case 0:  return  X + Y; case 1:  return -X + Y; case 2:  return  X - Y;
		case 3:  return -X - Y; case 4:  return  X + Z; case 5:  return -X + Z;
		case 6:  return  X - Z; case 7:  return -X - Z; case 8:  return  Y + Z;
		case 9:  return -Y + Z; case 10: return  Y - Z; default: return -Y - Z;
		}
	}

	FORCEINLINE double Fade(double T) { return T * T * T * (T * (T * 6.0 - 15.0) + 10.0); }

	double Perlin(const FVector& P, uint32 Seed)
	{
		const int32 X0 = FMath::FloorToInt32(P.X);
		const int32 Y0 = FMath::FloorToInt32(P.Y);
		const int32 Z0 = FMath::FloorToInt32(P.Z);
		const double FX = P.X - X0, FY = P.Y - Y0, FZ = P.Z - Z0;
		const double U = Fade(FX), V = Fade(FY), W = Fade(FZ);

		auto G = [&](int32 DX, int32 DY, int32 DZ)
		{
			return Grad(Hash(X0 + DX, Y0 + DY, Z0 + DZ, Seed), FX - DX, FY - DY, FZ - DZ);
		};

		const double L00 = FMath::Lerp(G(0, 0, 0), G(1, 0, 0), U);
		const double L10 = FMath::Lerp(G(0, 1, 0), G(1, 1, 0), U);
		const double L01 = FMath::Lerp(G(0, 0, 1), G(1, 0, 1), U);
		const double L11 = FMath::Lerp(G(0, 1, 1), G(1, 1, 1), U);
		return FMath::Lerp(FMath::Lerp(L00, L10, V), FMath::Lerp(L01, L11, V), W);
	}

	// FBM normalised into [0, 1] (Blender-style: base + detail octaves).
	double Fbm(const FVector& P, int32 Octaves, uint32 Seed)
	{
		double Sum = 0.0, Amp = 1.0, AmpSum = 0.0;
		FVector Pos = P;
		for (int32 I = 0; I < Octaves; ++I)
		{
			Sum += Amp * Perlin(Pos, Seed + static_cast<uint32>(I) * 0x51633E2Du);
			AmpSum += Amp;
			Amp *= 0.5;
			Pos *= 2.0;
		}
		// Perlin spans roughly ±0.87 in 3D; normalise then centre into [0,1].
		const double N = Sum / (AmpSum * 0.87);
		return FMath::Clamp(0.5 + 0.5 * N, 0.0, 1.0);
	}
}

FPCGElementPtr UGNueNoise3DSettings::CreateElement() const
{
	return MakeShared<FGNueNoise3DElement>();
}

EPCGPointNativeProperties FGNueNoise3DElement::GetPropertiesToAllocate(FPCGContext* Context) const
{
	const UGNueNoise3DSettings* Settings = Context ? Context->GetInputSettings<UGNueNoise3DSettings>() : nullptr;
	if (Settings && Settings->Output == EGNueNoiseOutput::ScaleMultiply)
	{
		return EPCGPointNativeProperties::Transform;
	}
	return EPCGPointNativeProperties::Density;
}

bool FGNueNoise3DElement::ExecuteInternal(FPCGContext* Context) const
{
	TRACE_CPUPROFILER_EVENT_SCOPE(FGNueNoise3DElement::Execute);
	check(Context);

	const UGNueNoise3DSettings* Settings = Context->GetInputSettings<UGNueNoise3DSettings>();
	check(Settings);

	FGNueNoise3DElement::ContextType* OpContext =
		static_cast<FGNueNoise3DElement::ContextType*>(Context);

	const bool bDensity = (Settings->Output == EGNueNoiseOutput::Density);
	// Blender samples object-space metres at frequency 'Scale'; our points are
	// world centimetres.
	const double Frequency = Settings->NoiseScale / 100.0;
	const int32 Octaves = FMath::Clamp(Settings->Detail, 1, 8);
	const uint32 Seed = static_cast<uint32>(Settings->NoiseSeed) * 0x9E3779B1u + 0x7F4A7C15u;
	const double OutMin = Settings->OutMin;
	const double OutMax = Settings->OutMax;
	const bool bX = Settings->bScaleX, bY = Settings->bScaleY, bZ = Settings->bScaleZ;

	return ExecutePointOperation(OpContext,
		[bDensity, Frequency, Octaves, Seed, OutMin, OutMax, bX, bY, bZ]
		(const UPCGBasePointData* InputData, UPCGBasePointData* OutputData, int32 StartIndex, int32 Count)
	{
		const TConstPCGValueRange<FTransform> InTransforms = InputData->GetConstTransformValueRange();
		TPCGValueRange<FTransform> OutTransforms = bDensity ? TPCGValueRange<FTransform>() : OutputData->GetTransformValueRange();
		TPCGValueRange<float> OutDensity = bDensity ? OutputData->GetDensityValueRange() : TPCGValueRange<float>();

		for (int32 Index = StartIndex; Index < (StartIndex + Count); ++Index)
		{
			const FVector Pos = InTransforms[Index].GetLocation() * Frequency;
			const double Noise = GNueNoise::Fbm(Pos, Octaves, Seed);
			const double Value = OutMin + Noise * (OutMax - OutMin);

			if (bDensity)
			{
				OutDensity[Index] = static_cast<float>(FMath::Clamp(Value, 0.0, 1.0));
			}
			else
			{
				FTransform& Transform = OutTransforms[Index];
				FVector Scale = Transform.GetScale3D();
				if (bX) { Scale.X *= Value; }
				if (bY) { Scale.Y *= Value; }
				if (bZ) { Scale.Z *= Value; }
				Transform.SetScale3D(Scale);
			}
		}
		return true;
	});
}

#undef LOCTEXT_NAMESPACE
