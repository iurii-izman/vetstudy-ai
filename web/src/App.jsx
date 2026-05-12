import { useState } from 'react'
import { Dashboard } from './components/Dashboard'
import { LoginScreen } from './screens/auth/LoginScreen'

export default function App() {
  const [token, setToken] = useState(localStorage.getItem('vetstudy-token') || '')

  const handleAuth = (newToken) => {
    localStorage.setItem('vetstudy-token', newToken)
    setToken(newToken)
  }

  const handleLogout = () => {
    localStorage.removeItem('vetstudy-token')
    setToken('')
  }

  if (!token) return <LoginScreen onAuth={handleAuth} />
  return <Dashboard token={token} onLogout={handleLogout} />
}
