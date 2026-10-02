import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import App from './App.jsx'
import { AuthProvider } from './auth/AuthContext.jsx'
import ProtectedRoute from './auth/ProtectedRoute.jsx'
import Landing from './pages/Landing.jsx'
import Login from './pages/Login.jsx'
// [暫時關閉] 註冊功能停用
// import Register from './pages/Register.jsx'
import VerifyEmail from './pages/VerifyEmail.jsx'
import RequestReset from './pages/RequestReset.jsx'
import ResetPassword from './pages/ResetPassword.jsx'
import Account from './pages/Account.jsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          {/* [暫時關閉] 註冊功能停用；舊連結導回登入頁，恢復時改回 element={<Register />} */}
          <Route path="/register" element={<Navigate to="/login" replace />} />
          <Route path="/verify-email" element={<VerifyEmail />} />
          <Route path="/forgot" element={<RequestReset />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route path="/account" element={<ProtectedRoute><Account /></ProtectedRoute>} />
          <Route path="/app" element={<ProtectedRoute><App /></ProtectedRoute>} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
