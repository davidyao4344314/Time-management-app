import './Home.css'

const activities = [
  {
    id: 1,
    name: 'Physics study',
    startTime: '9:00 AM',
    endTime: '10:00 AM',
    category: 'Physics',
  },
  {
    id: 2,
    name: 'Lunch break',
    startTime: '12:00 PM',
    endTime: '12:30 PM',
  },
  {
    id: 3,
    name: 'Maths revision',
    startTime: '3:00 PM',
    endTime: '4:00 PM',
    category: 'Mathematics',
  },
]

function Home() {
  return (
    <main className="page">
      <h2>Home</h2>

      <section className="today-activities">
        <h3>Today's Activities</h3>

        {activities.length === 0 ? (
          <p>No activities scheduled for today.</p>
        ) : (
          <ul className="activity-list">
            {activities.map((activity) => (
              <li className="activity-card" key={activity.id}>
                <div>
                  <h4>{activity.name}</h4>
                  {activity.category && <p>{activity.category}</p>}
                </div>
                <p className="activity-time">
                  {activity.startTime} – {activity.endTime}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  )
}

export default Home
