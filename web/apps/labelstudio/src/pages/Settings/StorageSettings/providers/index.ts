import localFilesProvider from "./localFiles";

// AOI 二开仅保留本地文件/上传导入；外部云存储（S3/GCS/Azure/Redis）已剥离。
export const providers = {
  localfiles: localFilesProvider,
};
