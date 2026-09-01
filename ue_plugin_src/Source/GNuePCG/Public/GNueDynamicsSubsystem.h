// GNue Dynamics — per-frame controller sync for shader-driven effects.
//
// The importer moves continuous modulation (proximity collapse) out of the
// PCG graph and into a World Position Offset material, so the effect reacts
// every frame without regenerating. The material reads the controller's
// position from a Material Parameter Collection named
//   MPC_GNueCtrl_<Tag>   (one per Blender controller object / actor tag)
// and this subsystem keeps that collection in sync with whichever actor in
// the world carries <Tag>. Runs in the editor viewport and at runtime.

#pragma once

#include "Subsystems/WorldSubsystem.h"
#include "UObject/WeakObjectPtr.h"

#include "GNueDynamicsSubsystem.generated.h"

class UMaterialParameterCollection;

USTRUCT()
struct FGNueControllerBinding
{
	GENERATED_BODY()

	UPROPERTY()
	TObjectPtr<UMaterialParameterCollection> Collection = nullptr;

	FName Tag;
	TWeakObjectPtr<AActor> Actor;
	double NextActorSearch = 0.0;
	bool bWasTracking = false;   // log only on found/lost transitions
};

UCLASS()
class GNUEPCG_API UGNueDynamicsSubsystem : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	//~Begin USubsystem
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	//~End USubsystem

	//~Begin FTickableGameObject
	virtual void Tick(float DeltaTime) override;
	virtual bool IsTickableInEditor() const override { return true; }
	virtual TStatId GetStatId() const override;
	//~End FTickableGameObject

	/** Collections are discovered by name prefix under this content path. */
	static const TCHAR* CollectionPrefix() { return TEXT("MPC_GNueCtrl_"); }
	static const TCHAR* PositionParameter() { return TEXT("Position"); }

private:
	void DiscoverCollections();
	AActor* FindTaggedActor(FName Tag) const;

	UPROPERTY()
	TArray<FGNueControllerBinding> Bindings;

	double NextDiscovery = 0.0;
};
