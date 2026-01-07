import React, { useState, useEffect } from 'react';
import { io } from 'socket.io-client';
import axios from 'axios';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, PieChart, Pie, Cell
} from 'recharts';
import './App.css';

const SIMULATION_URL = process.env.REACT_APP_SIMULATION_URL || 'http://localhost:5000';
const MONITORING_URL = process.env.REACT_APP_MONITORING_URL || 'http://localhost:3000';

const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884D8'];

function App() {
  const [socket, setSocket] = useState(null);
  const [connected, setConnected] = useState(false);
  const [simulationState, setSimulationState] = useState(null);
  const [events, setEvents] = useState([]);
  const [metrics, setMetrics] = useState([]);
  const [activeUsers, setActiveUsers] = useState(0);
  const [dashboardData, setDashboardData] = useState(null);

  // Initialize socket connection
  useEffect(() => {
    const newSocket = io(SIMULATION_URL);
    
    newSocket.on('connect', () => {
      console.log('Connected to simulation server');
      setConnected(true);
    });

    newSocket.on('disconnect', () => {
      console.log('Disconnected from simulation server');
      setConnected(false);
    });

    newSocket.on('status', (data) => {
      console.log('Status:', data.message);
      addEvent({ type: 'status', message: data.message, timestamp: new Date() });
    });

    newSocket.on('event', (data) => {
      console.log('Event:', data);
      addEvent({ type: 'event', ...data, timestamp: new Date() });
    });

    setSocket(newSocket);

    return () => newSocket.close();
  }, []);

  // Fetch simulation state periodically
  useEffect(() => {
    const fetchState = async () => {
      try {
        const response = await axios.get(`${SIMULATION_URL}/state`);
        setSimulationState(response.data);
        updateMetrics(response.data);
      } catch (error) {
        console.error('Error fetching state:', error);
      }
    };

    fetchState();
    const interval = setInterval(fetchState, 5000);
    return () => clearInterval(interval);
  }, []);

  // Fetch dashboard data
  useEffect(() => {
    const fetchDashboard = async () => {
      try {
        const response = await axios.get(`${MONITORING_URL}/api/analytics/dashboard`);
        setDashboardData(response.data.data);
      } catch (error) {
        console.error('Error fetching dashboard:', error);
      }
    };

    fetchDashboard();
    const interval = setInterval(fetchDashboard, 10000);
    return () => clearInterval(interval);
  }, []);

  // Fetch active users
  useEffect(() => {
    const fetchActiveUsers = async () => {
      try {
        const response = await axios.get(`${MONITORING_URL}/api/users/active`);
        setActiveUsers(response.data.activeUsers);
      } catch (error) {
        console.error('Error fetching active users:', error);
      }
    };

    fetchActiveUsers();
    const interval = setInterval(fetchActiveUsers, 30000);
    return () => clearInterval(interval);
  }, []);

  const addEvent = (event) => {
    setEvents(prev => [event, ...prev].slice(0, 50));
  };

  const updateMetrics = (state) => {
    if (!state || !state.universes) return;

    const timestamp = new Date().toLocaleTimeString();
    const u1 = state.universes.U1;
    
    if (!u1) return;

    const totalAttention = Object.values(u1.civilizations).reduce(
      (sum, civ) => sum + (civ.resources?.attention || 0), 0
    );
    const totalCompute = Object.values(u1.civilizations).reduce(
      (sum, civ) => sum + (civ.resources?.compute || 0), 0
    );
    const totalMemoryNodes = Object.values(u1.civilizations).reduce(
      (sum, civ) => sum + (civ.resources?.memory_nodes || 0), 0
    );

    const newMetric = {
      timestamp,
      attention: totalAttention,
      compute: totalCompute,
      memoryNodes: totalMemoryNodes,
      civilizations: Object.keys(u1.civilizations).length
    };

    setMetrics(prev => [...prev.slice(-19), newMetric]);
  };

  const startSimulation = () => {
    if (socket) {
      socket.emit('start_simulation');
    }
  };

  const stopSimulation = () => {
    if (socket) {
      socket.emit('stop_simulation');
    }
  };

  const runCycles = async (cycles) => {
    try {
      await axios.post(`${SIMULATION_URL}/simulate/${cycles}`);
      addEvent({ type: 'info', message: `Ran ${cycles} simulation cycles`, timestamp: new Date() });
    } catch (error) {
      console.error('Error running cycles:', error);
    }
  };

  const getFactionData = () => {
    if (!simulationState?.universes?.U1?.factions) return [];
    const factions = simulationState.universes.U1.factions;
    return Object.entries(factions).map(([name, value]) => ({ name, value }));
  };

  return (
    <div className="App">
      <header className="App-header">
        <h1>🌀 CycleKernel - Memory Evolution Dashboard</h1>
        <div className="connection-status">
          <span className={connected ? 'status-connected' : 'status-disconnected'}>
            {connected ? '🟢 Connected' : '🔴 Disconnected'}
          </span>
          <span className="active-users">👥 Active Users: {activeUsers}</span>
        </div>
      </header>

      <div className="controls">
        <button onClick={startSimulation} disabled={!connected}>▶️ Start Simulation</button>
        <button onClick={stopSimulation} disabled={!connected}>⏸️ Stop Simulation</button>
        <button onClick={() => runCycles(10)} disabled={!connected}>⏭️ Run 10 Cycles</button>
        <button onClick={() => runCycles(100)} disabled={!connected}>⏭️ Run 100 Cycles</button>
      </div>

      <div className="dashboard">
        <div className="stats-grid">
          <div className="stat-card">
            <h3>Total Civilizations</h3>
            <div className="stat-value">{simulationState?.total_civilizations || 0}</div>
          </div>
          <div className="stat-card">
            <h3>Total Chats</h3>
            <div className="stat-value">{dashboardData?.totalChats || 0}</div>
          </div>
          <div className="stat-card">
            <h3>Simulation Snapshots</h3>
            <div className="stat-value">{dashboardData?.totalSnapshots || 0}</div>
          </div>
          <div className="stat-card">
            <h3>Cycle Count</h3>
            <div className="stat-value">{simulationState?.universes?.U1?.cycle_count || 0}</div>
          </div>
        </div>

        <div className="charts-grid">
          <div className="chart-container">
            <h3>Resource Evolution Over Time</h3>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={metrics}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="timestamp" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="attention" stroke="#8884d8" name="Attention" />
                <Line type="monotone" dataKey="compute" stroke="#82ca9d" name="Compute" />
                <Line type="monotone" dataKey="memoryNodes" stroke="#ffc658" name="Memory Nodes" />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="chart-container">
            <h3>Faction Distribution</h3>
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={getFactionData()}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ name, value }) => `${name}: ${value}`}
                  outerRadius={80}
                  fill="#8884d8"
                  dataKey="value"
                >
                  {getFactionData().map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>

          <div className="chart-container">
            <h3>Civilization Count Over Time</h3>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={metrics}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="timestamp" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Bar dataKey="civilizations" fill="#8884d8" name="Civilizations" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="events-container">
          <h3>Recent Events</h3>
          <div className="events-list">
            {events.map((event, index) => (
              <div key={index} className={`event event-${event.type}`}>
                <span className="event-time">{event.timestamp.toLocaleTimeString()}</span>
                <span className="event-message">{event.message}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
