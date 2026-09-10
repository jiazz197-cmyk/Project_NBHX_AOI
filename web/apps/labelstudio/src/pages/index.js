import { ProjectsPage } from "./Projects/Projects";
import { HomePage } from "./Home/HomePage";
import { DatasetsPage } from "./Datasets/DatasetsPage";
import { TrainingPage } from "./Training/TrainingPage";
import { ReviewPage } from "./Review/ReviewPage";
import { SystemPage } from "./System/SystemPage";
import { OrganizationPage } from "./Organization";
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
  OrganizationPage,
  ModelsPage,
  pages.AccountSettingsPage,
].filter(Boolean);
