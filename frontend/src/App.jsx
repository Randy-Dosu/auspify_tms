import { Route, Routes } from 'react-router-dom'
import AppLayout from './components/AppLayout'
import ProtectedRoute from './auth/ProtectedRoute'
import LoginPage from './pages/LoginPage'
import { DashboardRedirect } from './pages/Dashboards'
import TeacherExamsPage from './pages/teacher/TeacherExamsPage'
import ExamEditorPage from './pages/teacher/ExamEditorPage'
import StudentExamsPage from './pages/student/StudentExamsPage'
import TakeExamPage from './pages/student/TakeExamPage'
import ResultPage from './pages/student/ResultPage'
import ProgressPage from './pages/student/ProgressPage'
import ExamReportPage from './pages/teacher/ExamReportPage'
import StudentReportPage from './pages/teacher/StudentReportPage'
import { FullPageMessage } from './components/ui'

/**
 * Application routes.
 *
 * /login is public. Everything else sits behind
 * <ProtectedRoute>, which redirects logged-out visitors to /login and blocks
 * wrong-role access with a 403 page.
 */
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<DashboardRedirect />} />
      <Route path="/login" element={<LoginPage />} />

      <Route
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/dashboard" element={<DashboardRedirect />} />

        {/* Teacher / admin */}
        <Route
          path="/teacher"
          element={
            <ProtectedRoute roles={['teacher', 'admin']}>
              <TeacherExamsPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/teacher/exams/:examId"
          element={
            <ProtectedRoute roles={['teacher', 'admin']}>
              <ExamEditorPage />
            </ProtectedRoute>
          }
        />

        <Route
          path="/teacher/reports/:examId"
          element={
            <ProtectedRoute roles={['teacher', 'admin']}>
              <ExamReportPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/teacher/students/:studentId"
          element={
            <ProtectedRoute roles={['teacher', 'admin']}>
              <StudentReportPage />
            </ProtectedRoute>
          }
        />

        {/* Student */}
        <Route
          path="/student"
          element={
            <ProtectedRoute roles={['student']}>
              <StudentExamsPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/student/attempts/:attemptId"
          element={
            <ProtectedRoute roles={['student']}>
              <TakeExamPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/student/results/:attemptId"
          element={
            <ProtectedRoute roles={['student']}>
              <ResultPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/student/progress"
          element={
            <ProtectedRoute roles={['student']}>
              <ProgressPage />
            </ProtectedRoute>
          }
        />
      </Route>

      <Route
        path="*"
        element={
          <FullPageMessage
            title="404 — Page not found"
            body="That page does not exist."
            linkTo="/dashboard"
            linkLabel="Back to dashboard"
          />
        }
      />
    </Routes>
  )
}
