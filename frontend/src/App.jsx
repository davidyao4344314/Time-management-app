import { useState } from 'react'
import './App.css'

function App() {
  const [count, setCount] = useState(0)

  return (
    <div>
      <h1>Activities Planner Test</h1>

      <p>React is running!</p>

      <button onClick={() => setCount(count + 1)}>
        Clicked {count} times
      </button>
    </div>
  )
}

export default App