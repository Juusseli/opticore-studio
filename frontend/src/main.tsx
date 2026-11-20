import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { ErrorBoundary } from './components/common/ErrorBoundary'
// Inter and JetBrains Mono are bundled (OFL), so every platform renders the same type
import '@fontsource-variable/inter'
import '@fontsource-variable/jetbrains-mono'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary name="OptiCore Studio" root>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
