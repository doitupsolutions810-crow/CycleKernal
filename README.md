# CycleKernel - Integrated Monitoring Platform

A powerful simulation and monitoring system that combines the **CycleKernel** simulation engine with **Grok Monitoring Platform** capabilities. This project enables real-time tracking of simulation health, memory evolution visualization, and persistent storage of chat history and simulation artifacts.

## 🌟 Features

### Core Capabilities

1. **Simulation Engine** (Python/Flask)
   - Multi-universe civilization simulation
   - ChatMemoryBridge for linking chat interactions to simulation state
   - Real-time resource management (Attention, Compute, Memory Nodes)
   - Belief system dynamics (Truth vs Deception)
   - WebSocket support for real-time updates

2. **Monitoring Backend** (Node.js/Express)
   - RESTful API for data access
   - MongoDB integration for persistent storage
   - Redis caching for performance optimization
   - Prometheus metrics export
   - Rate limiting and security hardening

3. **Visualization Frontend** (React)
   - Real-time dashboard with Recharts
   - Memory evolution charts
   - Faction distribution visualization
   - Event stream monitoring
   - Responsive design

4. **Infrastructure**
   - **Grafana**: Advanced metrics visualization
   - **Prometheus**: Time-series metrics collection
   - **MongoDB**: Persistent data storage
   - **Redis**: High-performance caching
   - **Docker Compose**: Orchestrated deployment

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Frontend (React)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │  Dashboard   │  │   Charts     │  │   Events     │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
┌───────▼────────┐  ┌──────▼──────┐  ┌───────▼────────┐
│  Simulation    │  │ Monitoring  │  │    Grafana     │
│   (Flask)      │  │  (Express)  │  │  (Dashboards)  │
│                │  │             │  │                │
│ • CycleKernel  │  │ • REST API  │  │ • Metrics Viz  │
│ • ChatBridge   │  │ • MongoDB   │  │ • Alerts       │
│ • WebSocket    │  │ • Redis     │  │                │
│ • Prometheus   │  │ • Metrics   │  │                │
└────────────────┘  └─────────────┘  └────────────────┘
        │                  │                  │
        └──────────────────┼──────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
┌───────▼────────┐  ┌──────▼──────┐  ┌───────▼────────┐
│  Prometheus    │  │   MongoDB   │  │     Redis      │
│ (Metrics DB)   │  │  (Storage)  │  │    (Cache)     │
└────────────────┘  └─────────────┘  └────────────────┘
```

## 📦 Project Structure

```
CycleKernel-Integrated/
├── backend/
│   ├── simulation_core.py      # Python simulation engine
│   ├── server.js                # Node.js monitoring server
│   ├── Dockerfile.sim           # Simulation container
│   ├── Dockerfile.mon           # Monitoring container
│   ├── requirements-sim.txt     # Python dependencies
│   └── package.json             # Node.js dependencies
├── frontend/
│   ├── src/
│   │   ├── App.js               # Main React component
│   │   ├── App.css              # Styling
│   │   ├── index.js             # Entry point
│   │   └── index.css            # Global styles
│   ├── public/
│   │   └── index.html           # HTML template
│   ├── Dockerfile               # Frontend container
│   ├── nginx.conf               # Nginx configuration
│   └── package.json             # Frontend dependencies
├── prometheus/
│   └── prometheus.yml           # Prometheus configuration
├── grafana/
│   └── dashboards/              # Grafana dashboard configs
├── logs/                        # Application logs
├── scripts/                     # Utility scripts
├── docs/                        # Documentation
├── docker-compose.yml           # Container orchestration
└── README.md                    # This file
```

## 🚀 Quick Start

### Prerequisites

- Docker (20.10+)
- Docker Compose (2.0+)
- Git

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/doitupsolutions810-crow/CycleKernal.git
   cd CycleKernal
   ```

2. **Start all services**
   ```bash
   docker-compose up -d
   ```

3. **Access the services**
   - **Frontend Dashboard**: http://localhost:8080
   - **Simulation API**: http://localhost:5000
   - **Monitoring API**: http://localhost:3000
   - **Grafana**: http://localhost:3001 (admin/admin)
   - **Prometheus**: http://localhost:9090

### Development Mode

For local development without Docker:

1. **Backend - Simulation**
   ```bash
   cd backend
   pip install -r requirements-sim.txt
   python simulation_core.py
   ```

2. **Backend - Monitoring**
   ```bash
   cd backend
   npm install
   node server.js
   ```

3. **Frontend**
   ```bash
   cd frontend
   npm install
   npm start
   ```

## 📊 API Endpoints

### Simulation API (Port 5000)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/metrics` | Prometheus metrics |
| GET | `/state` | Current simulation state |
| POST | `/simulate/<cycles>` | Run N simulation cycles |
| POST | `/chat/interact` | Process chat interaction |
| GET | `/chat/context/<user_id>` | Get user memory context |

### Monitoring API (Port 3000)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/metrics` | Prometheus metrics |
| POST | `/api/chat/save` | Save chat to database |
| GET | `/api/chat/history/:userId` | Get chat history |
| POST | `/api/simulation/snapshot` | Save simulation snapshot |
| GET | `/api/simulation/snapshots/:universeId` | Get snapshots |
| GET | `/api/users/active` | Get active users count |
| GET | `/api/analytics/dashboard` | Dashboard analytics |

## 🔧 Configuration

### Environment Variables

**Simulation Backend:**
- `FLASK_ENV`: Flask environment (default: `production`)
- `PYTHONUNBUFFERED`: Python output buffering (default: `1`)

**Monitoring Backend:**
- `NODE_ENV`: Node environment (default: `production`)
- `MONGODB_URI`: MongoDB connection string
- `REDIS_URL`: Redis connection URL
- `PORT`: Server port (default: `3000`)

**Frontend:**
- `REACT_APP_SIMULATION_URL`: Simulation API URL
- `REACT_APP_MONITORING_URL`: Monitoring API URL

### Docker Compose Services

All services are configured in `docker-compose.yml`:

- **simulation**: Python Flask simulation engine
- **monitoring**: Node.js Express monitoring server
- **mongodb**: MongoDB database
- **redis**: Redis cache
- **prometheus**: Metrics collection
- **grafana**: Metrics visualization
- **frontend**: React dashboard

## 📈 Monitoring & Metrics

### Prometheus Metrics

**Simulation Metrics:**
- `simulation_cycles_total`: Total simulation cycles
- `active_civilizations`: Number of active civilizations
- `total_attention`: Total attention resources
- `total_compute`: Total compute resources
- `chat_interactions_total`: Total chat interactions
- `simulation_cycle_duration_seconds`: Cycle duration histogram

**Monitoring Metrics:**
- `http_request_duration_seconds`: HTTP request duration
- `chat_history_total_size`: Chat history size
- `active_users_total`: Active users count

### Grafana Dashboards

Access Grafana at http://localhost:3001 with credentials:
- **Username**: `admin`
- **Password**: `admin`

Pre-configured dashboards include:
- Simulation health overview
- Resource evolution trends
- Chat interaction analytics
- System performance metrics

## 🧪 Testing

### Health Checks

```bash
# Simulation health
curl http://localhost:5000/health

# Monitoring health
curl http://localhost:3000/health
```

### API Testing

```bash
# Get simulation state
curl http://localhost:5000/state

# Run 10 simulation cycles
curl -X POST http://localhost:5000/simulate/10

# Process chat interaction
curl -X POST http://localhost:3000/api/chat/save \
  -H "Content-Type: application/json" \
  -d '{
    "userId": "test_user",
    "civId": "user_test_u",
    "message": "Hello",
    "response": "Hi there!",
    "metadata": {"attention": 60, "compute": 25}
  }'
```

## 🔐 Security

- **Rate Limiting**: 100 requests per 15 minutes per IP
- **Helmet.js**: Security headers for Express
- **CORS**: Configured for cross-origin requests
- **Environment Variables**: Sensitive data in env vars
- **Docker Networks**: Isolated container networking

## 📝 ChatMemoryBridge Integration

The **ChatMemoryBridge** class connects chat interactions to the simulation:

```python
# Process interaction
bridge.process_interaction(user_id, message, response)

# Get memory context
context = bridge.get_context_from_memory(user_id)
```

**Features:**
- Maps users to civilizations
- Updates resources (Attention +10, Compute +5)
- Influences belief systems
- Logs all interactions
- Emits real-time events

## 🛠️ Maintenance

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f simulation
docker-compose logs -f monitoring
```

### Restart Services

```bash
# All services
docker-compose restart

# Specific service
docker-compose restart simulation
```

### Stop Services

```bash
docker-compose down
```

### Clean Up

```bash
# Stop and remove containers, networks
docker-compose down

# Remove volumes (WARNING: deletes all data)
docker-compose down -v
```

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License.

## 🙏 Acknowledgments

- **CycleKernel**: Original simulation engine concept
- **Grok Monitoring Platform**: Monitoring stack inspiration
- **Recharts**: React charting library
- **Prometheus**: Metrics collection system
- **Grafana**: Metrics visualization platform

## 📧 Support

For issues, questions, or contributions:
- **GitHub Issues**: [Create an issue](https://github.com/doitupsolutions810-crow/CycleKernal/issues)
- **Documentation**: See `/docs` directory

---

**Built with ❤️ for simulation and monitoring excellence**
