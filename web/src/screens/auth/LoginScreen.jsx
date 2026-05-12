import { useState } from 'react'
import { api } from '../../api'

export function LoginScreen({ onAuth }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (event) => {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      const data = await api.login(password)
      onAuth(data.access_token)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <form onSubmit={submit} className="login-card" aria-label="Login form">
        <div className="brand-mark">VS</div>
        <h1>VetStudy AI Cabinet</h1>
        <p>Owner workspace for Telegram knowledge, cards, and topic control.</p>
        <label>
          Owner password
          <input
            autoFocus
            placeholder="Owner password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            aria-label="Owner password"
          />
        </label>
        <button className="primary-action" type="submit" disabled={busy}>
          {busy ? 'Signing in...' : 'Sign in'}
        </button>
        {error ? <p className="error">{error}</p> : null}
      </form>
    </div>
  )
}
