#include "GNueParamLibrary.h"

#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "PCGGraph.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "StructUtils/PropertyBag.h"
#include "StructUtils/StructView.h"
#include "UObject/Class.h"

namespace
{
	bool ReadVector(const TSharedPtr<FJsonValue>& Value, FVector& Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
		if (!Value.IsValid() || !Value->TryGetArray(Arr) || Arr->Num() < 3)
		{
			return false;
		}
		Out = FVector((*Arr)[0]->AsNumber(), (*Arr)[1]->AsNumber(), (*Arr)[2]->AsNumber());
		return true;
	}
}

int32 UGNueParamLibrary::DeclareParameters(UPCGGraph* Graph, const FString& JsonSpec,
	bool bResetExisting)
{
	if (!Graph)
	{
		UE_LOG(LogTemp, Error, TEXT("GNueParamLibrary: null graph"));
		return -1;
	}

	TArray<TSharedPtr<FJsonValue>> Entries;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(JsonSpec);
	if (!FJsonSerializer::Deserialize(Reader, Entries))
	{
		UE_LOG(LogTemp, Error, TEXT("GNueParamLibrary: JsonSpec is not a JSON array"));
		return -1;
	}

	const FInstancedPropertyBag* Bag = Graph->GetUserParametersStruct();
	TArray<FPropertyBagPropertyDesc> NewDescs;
	// (name, type, default json) for the second pass that writes defaults
	TArray<TTuple<FName, FString, TSharedPtr<FJsonValue>>> NewValues;

	for (const TSharedPtr<FJsonValue>& Entry : Entries)
	{
		const TSharedPtr<FJsonObject>* Obj = nullptr;
		if (!Entry.IsValid() || !Entry->TryGetObject(Obj))
		{
			continue;
		}
		const FName Name(*(*Obj)->GetStringField(TEXT("name")));
		const FString Type = (*Obj)->GetStringField(TEXT("type")).ToLower();
		if (Name.IsNone())
		{
			continue;
		}
		if (Bag && Bag->FindPropertyDescByName(Name))
		{
			if (bResetExisting)
			{
				NewValues.Emplace(Name, Type, (*Obj)->TryGetField(TEXT("default")));
			}
			continue; // existing: keep (or just rewrite the value when resetting)
		}

		if (Type == TEXT("float"))
		{
			NewDescs.Emplace(Name, EPropertyBagPropertyType::Double);
		}
		else if (Type == TEXT("int"))
		{
			NewDescs.Emplace(Name, EPropertyBagPropertyType::Int32);
		}
		else if (Type == TEXT("bool"))
		{
			NewDescs.Emplace(Name, EPropertyBagPropertyType::Bool);
		}
		else if (Type == TEXT("vector"))
		{
			NewDescs.Emplace(Name, EPropertyBagPropertyType::Struct, TBaseStructure<FVector>::Get());
		}
		else
		{
			UE_LOG(LogTemp, Warning, TEXT("GNueParamLibrary: unsupported type %s for %s"),
				*Type, *Name.ToString());
			continue;
		}
		NewValues.Emplace(Name, Type, (*Obj)->TryGetField(TEXT("default")));
	}

	if (NewValues.IsEmpty())
	{
		return 0;
	}

	Graph->Modify();
	if (!NewDescs.IsEmpty())
	{
		const EPropertyBagAlterationResult AddResult = Graph->AddUserParameters(NewDescs);
		if (AddResult != EPropertyBagAlterationResult::Success)
		{
			UE_LOG(LogTemp, Error, TEXT("GNueParamLibrary: AddUserParameters failed (%d)"),
				static_cast<int32>(AddResult));
			return -1;
		}
	}

	Graph->UpdateUserParametersStruct([&NewValues](FInstancedPropertyBag& InBag)
	{
		for (const TTuple<FName, FString, TSharedPtr<FJsonValue>>& Value : NewValues)
		{
			const TSharedPtr<FJsonValue>& Json = Value.Get<2>();
			if (!Json.IsValid())
			{
				continue;
			}
			const FName& Name = Value.Get<0>();
			const FString& Type = Value.Get<1>();
			if (Type == TEXT("float"))
			{
				InBag.SetValueDouble(Name, Json->AsNumber());
			}
			else if (Type == TEXT("int"))
			{
				InBag.SetValueInt32(Name, static_cast<int32>(Json->AsNumber()));
			}
			else if (Type == TEXT("bool"))
			{
				InBag.SetValueBool(Name, Json->AsBool());
			}
			else if (Type == TEXT("vector"))
			{
				FVector Vec;
				if (ReadVector(Json, Vec))
				{
					InBag.SetValueStruct(Name, FConstStructView::Make(Vec));
				}
			}
		}
	});

	Graph->MarkPackageDirty();
	UE_LOG(LogTemp, Log, TEXT("GNueParamLibrary: declared %d (reset %d) parameter(s) on %s"),
		NewDescs.Num(), NewValues.Num() - NewDescs.Num(), *Graph->GetName());
	return NewValues.Num();
}
