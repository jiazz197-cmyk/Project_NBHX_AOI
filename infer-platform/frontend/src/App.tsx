import { Routes, Route, Navigate } from 'react-router-dom';
import AppLayout from './components/AppLayout';
import Dashboard from './pages/Dashboard';
import Inspections from './pages/Inspections';
import Reports from './pages/Reports';
import Stations from './pages/Stations';
import System from './pages/System';

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/inspections" element={<Inspections />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/stations" element={<Stations />} />
        <Route path="/system" element={<System />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}