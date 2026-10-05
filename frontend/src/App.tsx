import { Navigate, Route, Routes } from 'react-router-dom'

import { AppShell } from '@/components/app-shell'
import { Toaster } from '@/components/ui/sonner'
import { MatchesPage } from '@/pages/matches'
import { PipelinePage } from '@/pages/pipeline'
import { ProfilePage } from '@/pages/profile'
import { RunsPage } from '@/pages/runs'
import { SettingsPage } from '@/pages/settings'
import { TodayPage } from '@/pages/today'
import { WelcomePage } from '@/pages/welcome'

function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<TodayPage />} />
        <Route path="/welcome" element={<WelcomePage />} />
        <Route path="/matches" element={<MatchesPage />} />
        <Route path="/applications" element={<PipelinePage />} />
        <Route path="/pipeline" element={<Navigate to="/applications" replace />} />
        <Route path="/runs" element={<RunsPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <Toaster position="bottom-right" />
    </AppShell>
  )
}

export default App
