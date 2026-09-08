import { useQuery } from "@tanstack/react-query";
import { useAPI } from "apps/labelstudio/src/providers/ApiProvider";
import { useCallback, useMemo } from "react";

function useStorages(target: "import" | "export", projectId?: number) {
  const api = useAPI();
  const storagesQueryKey = ["storages", target, projectId];
  const { data, isLoading, isSuccess, refetch } = useQuery({
    queryKey: storagesQueryKey,
    enabled: projectId !== undefined,
    async queryFn() {
      const result = await api.callApi("listStorages", {
        params: { project: projectId, target },
        errorFilter: () => true,
      });

      if (!result?.$meta.ok) return [];

      return result;
    },
  });

  return {
    storages: data,
    storagesLoading: isLoading,
    storagesLoaded: isSuccess,
    reloadStoragesList: () => refetch({ queryKey: storagesQueryKey }),
  };
}

function useStorageTypes(target: "import" | "export") {
  const api = useAPI();
  const storageTypesQueryKey = ["storage-types", target];
  const { data, isLoading, isSuccess, refetch } = useQuery({
    queryKey: storageTypesQueryKey,
    async queryFn() {
      const result = await api.callApi<{ title: string; name: string }[]>("storageTypes", {
        params: { target },
        errorFilter: () => true,
      });

      if (!result?.$meta.ok) return [];

      return result;
    },
  });

  return {
    storageTypes: data,
    storageTypesLoading: isLoading,
    storageTypesLoaded: isSuccess,
    reloadStorageTypes: () => refetch({ queryKey: storageTypesQueryKey }),
  };
}

export function useStorageCard(target: "import" | "export", projectId?: number) {
  const { reloadStoragesList, ...storages } = useStorages(target, projectId);
  const { reloadStorageTypes, ...storageTypes } = useStorageTypes(target);

  const fetchStorages = useCallback(async () => {
    reloadStoragesList();
    reloadStorageTypes();
  }, [reloadStoragesList, reloadStorageTypes]);

  const loading = useMemo(
    () => storageTypes.storageTypesLoading || storages.storagesLoading,
    [storageTypes.storageTypesLoading, storages.storagesLoading],
  );
  const loaded = useMemo(
    () => storageTypes.storageTypesLoaded || storages.storagesLoaded,
    [storageTypes.storageTypesLoaded, storages.storagesLoaded],
  );

  return {
    ...storages,
    ...storageTypes,
    loaded,
    loading,
    fetchStorages,
  };
}
