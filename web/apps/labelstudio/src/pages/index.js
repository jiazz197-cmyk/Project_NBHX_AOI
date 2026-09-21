import { ProjectsPage } from "./Projects/Projects";
import { HomePage } from "./Home/HomePage";
import { DatasetsPage } from "./Datasets/DatasetsPage";
import { TrainingPage } from "./Training/TrainingPage";
import { ReviewPage } from "./Review/ReviewPage";
import { SystemPage } from "./System/SystemPage";
import { OrganizationAdminPage } from "./OrganizationAdmin/OrganizationAdminPage";
import { ModelsPage } from "./Organization/Models/ModelsPage";
import { pages } from "@humansignal/app-common";

// AOI 二开页面（注入点 4，见 CHANGES.md）
export const Pages = [
  HomePage,
  ProjectsPage,
  DatasetsPage,
  TrainingPage,
  ReviewPage,
  SystemPage,
  OrganizationAdminPage,
  ModelsPage,
  pages.AccountSettingsPage,
].filter(Boolean);
