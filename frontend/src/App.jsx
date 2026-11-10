import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useStore } from './store'
import Layout from './components/Layout'
import { Login, Register } from './pages/Auth'
import Dashboard from './pages/Dashboard'
import Organizations from './pages/Organizations'
import Members from './pages/Members'
import Events from './pages/Events'
import EventDetails from './pages/EventDetails'
import CalendarPage from './pages/Calendar'
import Sessions from './pages/Sessions'
import Resources from './pages/Resources'
import Bookings from './pages/Bookings'
import Registrations from './pages/Registrations'
import { AttendanceHub, Notifications, Profile, Settings } from './pages/Misc'

function Protected({ children }) {
  const access = useStore((s) => s.access), loc = useLocation()
  return access ? children : <Navigate to="/login" replace state={{ from: loc.pathname }} />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route element={<Protected><Layout /></Protected>}>
        <Route index element={<Dashboard />} />
        <Route path="organizations" element={<Organizations />} />
        <Route path="members" element={<Members />} />
        <Route path="events" element={<Events />} />
        <Route path="events/:id" element={<EventDetails />} />
        <Route path="calendar" element={<CalendarPage />} />
        <Route path="sessions" element={<Sessions />} />
        <Route path="resources" element={<Resources />} />
        <Route path="bookings" element={<Bookings />} />
        <Route path="registrations" element={<Registrations />} />
        <Route path="attendance" element={<AttendanceHub />} />
        <Route path="notifications" element={<Notifications />} />
        <Route path="profile" element={<Profile />} />
        <Route path="settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
