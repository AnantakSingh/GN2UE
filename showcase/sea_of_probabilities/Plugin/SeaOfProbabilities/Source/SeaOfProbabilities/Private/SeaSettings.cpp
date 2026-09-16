// Settings round-trip, SaveGame and live look application for ASeaOfProbabilitiesActor.
// Keys are the web version's exact names (spec section 3) so JSON pasted between the
// two builds just works; keys we don't own (sound, intro, phrase...) pass through.
#include "SeaOfProbabilitiesActor.h"
#include "SeaCameraPawn.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "Kismet/GameplayStatics.h"
#include "Kismet/KismetMaterialLibrary.h"
#include "Engine/DirectionalLight.h"
#include "Engine/SkyLight.h"
#include "Engine/PostProcessVolume.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/SkyLightComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "EngineUtils.h"
#include "Engine/World.h"

DEFINE_LOG_CATEGORY_STATIC(LogSeaSettings, Display, All);

static const TCHAR* SAVE_SLOT = TEXT("dice-ocean-params-v2");

static FString HexOf(const FLinearColor& C)
{
	const FColor S = C.ToFColorSRGB();
	return FString::Printf(TEXT("#%02x%02x%02x"), S.R, S.G, S.B);
}

static bool ColorOf(const FString& Hex, FLinearColor& Out)
{
	FString H = Hex.TrimStartAndEnd();
	if (H.StartsWith(TEXT("#"))) H.RightChopInline(1);
	if (H.Len() != 6) return false;
	const uint8 R = FParse::HexDigit(H[0]) * 16 + FParse::HexDigit(H[1]);
	const uint8 G = FParse::HexDigit(H[2]) * 16 + FParse::HexDigit(H[3]);
	const uint8 B = FParse::HexDigit(H[4]) * 16 + FParse::HexDigit(H[5]);
	Out = FLinearColor(FColor(R, G, B));      // sRGB -> linear
	return true;
}

// ------------------------------------------------------------------ key table

struct FSeaKey
{
	const TCHAR* Key;
	TFunction<void(const ASeaOfProbabilitiesActor&, TSharedRef<FJsonObject>)> Get;
	TFunction<bool(ASeaOfProbabilitiesActor&, const TSharedPtr<FJsonValue>&)> Set;
};

#define SEA_NUM(K, M) { TEXT(K), [](const ASeaOfProbabilitiesActor& A, TSharedRef<FJsonObject> O){ O->SetNumberField(TEXT(K), A.M); }, \
	[](ASeaOfProbabilitiesActor& A, const TSharedPtr<FJsonValue>& V){ double D; if (!V->TryGetNumber(D)) return false; A.M = (decltype(A.M))D; return true; } }
#define SEA_BOOL(K, M) { TEXT(K), [](const ASeaOfProbabilitiesActor& A, TSharedRef<FJsonObject> O){ O->SetBoolField(TEXT(K), A.M); }, \
	[](ASeaOfProbabilitiesActor& A, const TSharedPtr<FJsonValue>& V){ bool B; if (!V->TryGetBool(B)) return false; A.M = B; return true; } }
#define SEA_COL(K, M) { TEXT(K), [](const ASeaOfProbabilitiesActor& A, TSharedRef<FJsonObject> O){ O->SetStringField(TEXT(K), HexOf(A.M)); }, \
	[](ASeaOfProbabilitiesActor& A, const TSharedPtr<FJsonValue>& V){ FString S; if (!V->TryGetString(S)) return false; return ColorOf(S, A.M); } }

static const TArray<FSeaKey>& Keys()
{
	static const TArray<FSeaKey> K = {
		SEA_NUM("cols", Cols), SEA_NUM("rows", Rows), SEA_NUM("spacing", Spacing), SEA_NUM("bevel", Bevel), SEA_BOOL("redAce", bRedAce),
		SEA_NUM("waveSpeed", WaveSpeed), SEA_NUM("waveAmp", WaveAmp), SEA_NUM("waveScale", WaveScale), SEA_NUM("horizonR", HorizonR),
		SEA_NUM("pulseRadius", PulseRadius), SEA_NUM("pulseStrength", PulseStrength), SEA_NUM("springK", SpringK), SEA_NUM("springC", SpringC),
		SEA_NUM("activateAt", ActivateAt), SEA_NUM("fogNear", FogNear), SEA_NUM("fogFar", FogFar), SEA_BOOL("shadows", bShadows),
		SEA_NUM("splashRadius", SplashRadius), SEA_NUM("splashHeight", SplashHeight), SEA_NUM("splashSpin", SplashSpin), SEA_NUM("ringSpeed", RingSpeed),
		SEA_NUM("glowStrength", GlowStrength), SEA_NUM("glowSense", GlowSense), SEA_NUM("glowFade", GlowFade),
		SEA_COL("glowColorA", GlowColorA), SEA_COL("glowColorB", GlowColorB), SEA_COL("bgColor", BgColor), SEA_COL("diceColor", DiceColor),
		SEA_NUM("sunIntensity", SunIntensity), SEA_COL("sunColor", SunColor), SEA_NUM("sunAzimuth", SunAzimuth), SEA_NUM("sunElevation", SunElevation),
		SEA_NUM("hemiIntensity", HemiIntensity), SEA_NUM("envIntensity", EnvIntensity), SEA_NUM("exposure", Exposure),
		SEA_NUM("roughness", Roughness), SEA_NUM("metalness", Metalness), SEA_NUM("clearcoat", Clearcoat), SEA_NUM("clearcoatRough", ClearcoatRough),
		SEA_BOOL("idle", bIdle), SEA_NUM("idleAfter", IdleAfter), SEA_NUM("idleEvery", IdleEvery), SEA_NUM("idleStrength", IdleStrength),
		SEA_BOOL("idleCursor", bIdleCursor), SEA_NUM("idleCursorSpeed", IdleCursorSpeed), SEA_NUM("idleCursorStrength", IdleCursorStrength),
		SEA_BOOL("postFx", bPostFx), SEA_BOOL("bloom", bBloom), SEA_NUM("bloomStrength", BloomStrength), SEA_NUM("bloomThreshold", BloomThreshold),
		SEA_NUM("bloomRadius", BloomRadius), SEA_NUM("vignette", Vignette),
	};
	return K;
}

static ASeaCameraPawn* CameraPawnOf(UWorld* W)
{
	if (!W) return nullptr;
	for (TActorIterator<ASeaCameraPawn> It(W); It; ++It) return *It;
	return nullptr;
}

// ------------------------------------------------------------------ export / import

FString ASeaOfProbabilitiesActor::ExportSettingsJson() const
{
	TSharedRef<FJsonObject> O = Passthrough.IsValid() ? MakeShared<FJsonObject>(*Passthrough) : MakeShared<FJsonObject>();
	for (const FSeaKey& K : Keys()) K.Get(*this, O);
	// the web build's phrase string is kept for compatibility even though the reveal is out of scope
	if (!O->HasField(TEXT("phrase"))) O->SetStringField(TEXT("phrase"), TEXT("INFINITE POSSIBILITIES"));
	if (const ASeaCameraPawn* P = CameraPawnOf(GetWorld())) O->SetBoolField(TEXT("lockCamera"), P->bLockCamera);
	FString Out;
	const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer = TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Out);
	FJsonSerializer::Serialize(O, Writer);
	return Out;
}

bool ASeaOfProbabilitiesActor::ImportSettingsJson(const FString& Json, bool bApply)
{
	TSharedPtr<FJsonObject> O;
	const TSharedRef<TJsonReader<>> R = TJsonReaderFactory<>::Create(Json);
	if (!FJsonSerializer::Deserialize(R, O) || !O.IsValid())
	{
		UE_LOG(LogSeaSettings, Warning, TEXT("ImportSettingsJson: not valid JSON"));
		return false;
	}
	const int32 OldCols = Cols, OldRows = Rows; const float OldSpacing = Spacing; const bool OldAce = bRedAce;
	int32 Applied = 0, Unknown = 0;
	TSharedRef<FJsonObject> Rest = MakeShared<FJsonObject>();
	for (const auto& Pair : O->Values)
	{
		const FSeaKey* K = Keys().FindByPredicate([&](const FSeaKey& X) { return Pair.Key == X.Key; });
		if (K) { if (K->Set(*this, Pair.Value)) ++Applied; }
		else if (Pair.Key == TEXT("lockCamera")) { bool B; if (Pair.Value->TryGetBool(B)) if (ASeaCameraPawn* P = CameraPawnOf(GetWorld())) P->bLockCamera = B; }
		else { Rest->SetField(Pair.Key, Pair.Value); ++Unknown; }
	}
	Passthrough = Rest;
	UE_LOG(LogSeaSettings, Display, TEXT("ImportSettingsJson: %d applied, %d passed through"), Applied, Unknown);
	if (bApply)
	{
		if (Cols != OldCols || Rows != OldRows || Spacing != OldSpacing || bRedAce != OldAce) RebuildField();
		PushParametersToCollection();
		ApplyLookToWorld();
	}
	return true;
}

bool ASeaOfProbabilitiesActor::SetParam(const FString& Key, const FString& Value)
{
	// wrap as {"key": value} - numbers/bools bare, colours/strings quoted
	FString V = Value.TrimStartAndEnd();
	const bool bBare = V.IsNumeric() || V == TEXT("true") || V == TEXT("false");
	const FString Json = FString::Printf(TEXT("{\"%s\":%s}"), *Key, bBare ? *V : *FString::Printf(TEXT("\"%s\""), *V.Replace(TEXT("\""), TEXT(""))));
	TSharedPtr<FJsonObject> Keep = Passthrough;          // a single-key set must not wipe the passthrough
	const bool bOk = ImportSettingsJson(Json, true);
	if (Keep.IsValid()) { for (const auto& P : Passthrough->Values) Keep->SetField(P.Key, P.Value); Passthrough = Keep; }
	return bOk;
}

// ------------------------------------------------------------------ save / load / reset

bool ASeaOfProbabilitiesActor::SaveSettings()
{
	USeaSaveGame* S = Cast<USeaSaveGame>(UGameplayStatics::CreateSaveGameObject(USeaSaveGame::StaticClass()));
	if (!S) return false;
	S->Json = ExportSettingsJson();
	const bool bOk = UGameplayStatics::SaveGameToSlot(S, SAVE_SLOT, 0);
	UE_LOG(LogSeaSettings, Display, TEXT("SaveSettings -> %s (%d chars)"), bOk ? TEXT("ok") : TEXT("FAILED"), S->Json.Len());
	return bOk;
}

bool ASeaOfProbabilitiesActor::LoadSettings()
{
	if (!UGameplayStatics::DoesSaveGameExist(SAVE_SLOT, 0)) { UE_LOG(LogSeaSettings, Display, TEXT("LoadSettings: no save")); return false; }
	USeaSaveGame* S = Cast<USeaSaveGame>(UGameplayStatics::LoadGameFromSlot(SAVE_SLOT, 0));
	return S && ImportSettingsJson(S->Json, true);
}

void ASeaOfProbabilitiesActor::ResetDefaults()
{
	if (!DefaultsJson.IsEmpty()) ImportSettingsJson(DefaultsJson, true);
	UGameplayStatics::DeleteGameInSlot(SAVE_SLOT, 0);
	UE_LOG(LogSeaSettings, Display, TEXT("ResetDefaults"));
}

// ------------------------------------------------------------------ look -> level actors

void ASeaOfProbabilitiesActor::ApplyLookToWorld()
{
	UWorld* World = GetWorld();
	if (!World) return;
	for (TActorIterator<ADirectionalLight> It(World); It; ++It)
	{
		// spec 6.3: light at spherical (r 90, az, el) in three's frame, pointing at the origin
		const double Az = FMath::DegreesToRadians(SunAzimuth), El = FMath::DegreesToRadians(SunElevation);
		const FVector Pos3(90.0 * FMath::Cos(El) * FMath::Sin(Az), 90.0 * FMath::Sin(El), 90.0 * FMath::Cos(El) * FMath::Cos(Az));
		const FVector Pos(-Pos3.Z * 100.0, Pos3.X * 100.0, Pos3.Y * 100.0);
		It->SetActorLocationAndRotation(Pos, (-Pos).GetSafeNormal().Rotation());
		if (UDirectionalLightComponent* L = Cast<UDirectionalLightComponent>(It->GetLightComponent()))
		{
			L->SetIntensity(SunIntensity);
			L->SetLightColor(SunColor);
			L->SetCastShadows(bShadows);
		}
	}
	for (TActorIterator<ASkyLight> It(World); It; ++It)
	{
		if (USkyLightComponent* S = It->GetLightComponent())
		{
			S->SetIntensity(EnvIntensity);
			S->SetLowerHemisphereColor(FLinearColor(0.69f, 0.69f, 0.76f) * (HemiIntensity / 2.f));
		}
	}
	for (TActorIterator<APostProcessVolume> It(World); It; ++It)
	{
		FPostProcessSettings& P = It->Settings;
		P.bOverride_AutoExposureBias = true;
		P.AutoExposureBias = ExposureBiasAt052 + FMath::Log2(FMath::Max(Exposure, 0.001f) / 0.52f);
		P.bOverride_BloomIntensity = true;  P.BloomIntensity = (bPostFx && bBloom) ? BloomStrength : 0.f;
		P.bOverride_BloomThreshold = true;  P.BloomThreshold = BloomThreshold;
		P.bOverride_BloomSizeScale = true;  P.BloomSizeScale = BloomRadius * 10.f;   // three radius 0.4 ~ UE size scale 4
		// the vignette blendable reads MPC "Vignette"; postFx off -> 0
		break;
	}
	if (Collection)
	{
		UKismetMaterialLibrary::SetScalarParameterValue(this, Collection, TEXT("Vignette"), bPostFx ? Vignette : 0.f);
	}
	if (Dice) Dice->SetCastShadow(bShadows);
}
