import { BrowserRouter, Routes, Route } from "react-router-dom";
import { ChatProvider } from "@/context/ChatContext";
import { Layout } from "@/components/Layout";
import { HomePage } from "@/pages/HomePage";
import { StoriesPage } from "@/pages/StoriesPage";
import { StoryDetailPage } from "@/pages/StoryDetailPage";
import { RecommendationsPage } from "@/pages/RecommendationsPage";
import { PortfolioPage } from "@/pages/PortfolioPage";
import { PositionDetailPage } from "@/pages/PositionDetailPage";
import { InsightsPage } from "@/pages/InsightsPage";
import { SettingsPage } from "@/pages/SettingsPage";

export default function App() {
  return (
    <ChatProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<HomePage />} />
            <Route path="stories" element={<StoriesPage />} />
            <Route path="stories/:index" element={<StoryDetailPage />} />
            <Route path="recommendations" element={<RecommendationsPage />} />
            <Route path="portfolio" element={<PortfolioPage />} />
            <Route path="portfolio/:ticker" element={<PositionDetailPage />} />
            <Route path="insights" element={<InsightsPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ChatProvider>
  );
}
