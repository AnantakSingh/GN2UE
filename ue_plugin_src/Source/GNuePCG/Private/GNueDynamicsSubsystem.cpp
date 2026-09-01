#include "GNueDynamicsSubsystem.h"

#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Actor.h"
#include "Kismet/KismetMaterialLibrary.h"
#include "Materials/MaterialParameterCollection.h"

#include UE_INLINE_GENERATED_CPP_BY_NAME(GNueDynamicsSubsystem)

DEFINE_LOG_CATEGORY_STATIC(LogGNueDynamics, Display, All);

namespace
{
	constexpr double DiscoveryInterval = 2.0;    // new imports appear without restart
	constexpr double ActorSearchInterval = 0.5;  // re-find tagged actors cheaply
	// Matches the importer's PCG-side sentinel: no controller = "infinitely far"
	const FVector NoControllerPosition(0.0, 0.0, 1.0e7);
}

bool UGNueDynamicsSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	if (!Super::ShouldCreateSubsystem(Outer))
	{
		return false;
	}
	const UWorld* World = Cast<UWorld>(Outer);
	return World && (World->WorldType == EWorldType::Game || World->WorldType == EWorldType::PIE
		|| World->WorldType == EWorldType::Editor);
}

void UGNueDynamicsSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	DiscoverCollections();
	UE_LOG(LogGNueDynamics, Display,
		TEXT("[GNueDynamics] subsystem active (%d controller collection(s) found)"),
		Bindings.Num());
}

TStatId UGNueDynamicsSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UGNueDynamicsSubsystem, STATGROUP_Tickables);
}

void UGNueDynamicsSubsystem::DiscoverCollections()
{
	IAssetRegistry& Registry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry").Get();
	TArray<FAssetData> Assets;
	Registry.GetAssetsByClass(UMaterialParameterCollection::StaticClass()->GetClassPathName(), Assets);

	for (const FAssetData& Asset : Assets)
	{
		const FString Name = Asset.AssetName.ToString();
		if (!Name.StartsWith(CollectionPrefix()))
		{
			continue;
		}
		const bool bKnown = Bindings.ContainsByPredicate([&Asset](const FGNueControllerBinding& B)
		{
			return B.Collection && B.Collection->GetFName() == Asset.AssetName;
		});
		if (bKnown)
		{
			continue;
		}
		if (UMaterialParameterCollection* MPC = Cast<UMaterialParameterCollection>(Asset.GetAsset()))
		{
			FGNueControllerBinding& Binding = Bindings.AddDefaulted_GetRef();
			Binding.Collection = MPC;
			Binding.Tag = FName(*Name.RightChop(FCString::Strlen(CollectionPrefix())));
		}
	}
}

AActor* UGNueDynamicsSubsystem::FindTaggedActor(FName Tag) const
{
	UWorld* World = GetWorld();
	if (!World)
	{
		return nullptr;
	}
	for (TActorIterator<AActor> It(World); It; ++It)
	{
		if (It->ActorHasTag(Tag))
		{
			return *It;
		}
	}
	return nullptr;
}

void UGNueDynamicsSubsystem::Tick(float DeltaTime)
{
	UWorld* World = GetWorld();
	if (!World)
	{
		return;
	}
	const double Now = FPlatformTime::Seconds();
	if (Now >= NextDiscovery)
	{
		NextDiscovery = Now + DiscoveryInterval;
		DiscoverCollections();
	}

	for (FGNueControllerBinding& Binding : Bindings)
	{
		if (!Binding.Collection)
		{
			continue;
		}
		if (!Binding.Actor.IsValid() && Now >= Binding.NextActorSearch)
		{
			Binding.NextActorSearch = Now + ActorSearchInterval;
			Binding.Actor = FindTaggedActor(Binding.Tag);
		}
		const bool bTracking = Binding.Actor.IsValid();
		if (bTracking != Binding.bWasTracking)
		{
			Binding.bWasTracking = bTracking;
			UE_LOG(LogGNueDynamics, Display, TEXT("[GNueDynamics] tag '%s' %s"),
				*Binding.Tag.ToString(),
				bTracking ? *FString::Printf(TEXT("-> tracking actor '%s'"), *Binding.Actor->GetActorLabel())
						  : TEXT("-> no actor (effect at rest)"));
		}
		const FVector Pos = bTracking ? Binding.Actor->GetActorLocation() : NoControllerPosition;
		UKismetMaterialLibrary::SetVectorParameterValue(World, Binding.Collection, PositionParameter(),
			FLinearColor(static_cast<float>(Pos.X), static_cast<float>(Pos.Y), static_cast<float>(Pos.Z), 1.0f));
	}
}
