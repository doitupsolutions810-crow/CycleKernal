# CycleKernel Architecture Documentation

## Overview

The CycleKernel-Integrated platform is a comprehensive simulation and monitoring system that combines real-time simulation capabilities with enterprise-grade monitoring infrastructure. This document provides detailed architectural insights into the system design, component interactions, and data flow.

## System Architecture

### High-Level Architecture

The system follows a **microservices architecture** with the following key components:

1. **Frontend Layer**: React-based dashboard for visualization
2. **Application Layer**: Dual backend services (Python + Node.js)
3. **Data Layer**: MongoDB for persistence, Redis for caching
4. **Monitoring Layer**: Prometheus + Grafana for observability
5. **Orchestration Layer**: Docker Compose for container management

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENT LAYER                             │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Web Browser (React SPA)                                  │  │
│  │  • Dashboard UI                                           │  │
│  │  • Real-time Charts (Recharts)                           │  │
│  │  • WebSocket Client (Socket.io)                          │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP/WebSocket
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      APPLICATION LAYER                          │
│  ┌────────────────────────┐    ┌────────────────────────────┐  │
│  │  Simulation Backend    │    │  Monitoring Backend        │  │
│  │  (Python/Flask)        │    │  (Node.js/Express)         │  │
│  │                        │    │                            │  │
│  │  • CycleKernel Engine  │    │  • REST API                │  │
│  │  • ChatMemoryBridge    │    │  • Data Aggregation        │  │
│  │  • WebSocket Server    │    │  • Analytics Engine        │  │
│  │  • Prometheus Exporter │    │  • Prometheus Exporter     │  │
│  └────────────────────────┘    └────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ TCP/IP
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         DATA LAYER                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐ │
│  │   MongoDB    │  │    Redis     │  │   Prometheus TSDB    │ │
│  │              │  │              │  │                      │ │
│  │  • Chat Hist │  │  • Session   │  │  • Metrics Storage   │ │
│  │  • Snapshots │  │  • Cache     │  │  • Time Series Data  │ │
│  │  • Analytics │  │  • Queue     │  │  • Query Engine      │ │
│  └──────────────┘  └──────────────┘  └──────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     VISUALIZATION LAYER                         │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Grafana                                                  │  │
│  │  • Pre-built Dashboards                                  │  │
│  │  • Custom Queries                                        │  │
│  │  • Alerting Rules                                        │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Simulation Backend (Python/Flask)

**Purpose**: Core simulation engine with real-time capabilities

**Key Classes**:

- **CycleKernel**: Main simulation orchestrator
  - Manages multiple universes
  - Executes simulation cycles
  - Maintains audit logs
  - Exposes state via API

- **Universe**: Container for civilizations
  - Tracks civilizations and factions
  - Runs simulation cycles
  - Manages myths and events

- **ChatMemoryBridge**: Integration layer
  - Maps users to civilizations
  - Processes chat interactions
  - Updates simulation state
  - Retrieves memory context

**Technologies**:
- Flask: Web framework
- Flask-SocketIO: WebSocket support
- NumPy: Numerical computations
- Prometheus Client: Metrics export

**Endpoints**:
- `/health`: Health check
- `/metrics`: Prometheus metrics
- `/state`: Current simulation state
- `/simulate/<cycles>`: Run simulation
- `/chat/interact`: Process chat
- `/chat/context/<user_id>`: Get context

### 2. Monitoring Backend (Node.js/Express)

**Purpose**: Data persistence, caching, and analytics

**Key Features**:

- **RESTful API**: Standard HTTP endpoints
- **MongoDB Integration**: Persistent storage
- **Redis Caching**: Performance optimization
- **Prometheus Metrics**: Observability
- **Rate Limiting**: Security protection
- **Error Handling**: Robust error management

**Technologies**:
- Express: Web framework
- Mongoose: MongoDB ODM
- Redis Client: Caching layer
- Prom-Client: Metrics export
- Helmet: Security headers
- Morgan: HTTP logging

**Data Models**:

```javascript
// ChatHistory Schema
{
  userId: String,
  civId: String,
  message: String,
  response: String,
  timestamp: Date,
  metadata: {
    attention: Number,
    compute: Number,
    memoryNodes: Number,
    belief: { truth: Number, deception: Number }
  }
}

// SimulationSnapshot Schema
{
  universeId: String,
  cycleCount: Number,
  timestamp: Date,
  civilizations: Mixed,
  factions: Mixed,
  metrics: {
    totalAttention: Number,
    totalCompute: Number,
    totalMemoryNodes: Number
  }
}
```

### 3. Frontend (React)

**Purpose**: User interface and visualization

**Key Components**:

- **App.js**: Main application component
  - Socket.io connection management
  - State management
  - API integration
  - Real-time updates

- **Charts**: Data visualization
  - LineChart: Resource evolution
  - PieChart: Faction distribution
  - BarChart: Civilization count

**Technologies**:
- React: UI framework
- Recharts: Charting library
- Socket.io Client: WebSocket client
- Axios: HTTP client

**State Management**:
- useState: Local component state
- useEffect: Side effects and lifecycle
- Real-time updates via WebSocket

### 4. Data Layer

#### MongoDB

**Purpose**: Persistent data storage

**Collections**:
- `chathistories`: Chat interaction logs
- `simulationsnapshots`: Simulation state snapshots

**Features**:
- Indexed queries for performance
- Aggregation pipeline for analytics
- Automatic timestamps
- Schema validation

#### Redis

**Purpose**: High-performance caching

**Use Cases**:
- Session storage
- Recent chat caching
- Query result caching
- Rate limiting counters

**Configuration**:
- Append-only file (AOF) persistence
- Key expiration (TTL)
- Pub/Sub for events

### 5. Monitoring Layer

#### Prometheus

**Purpose**: Metrics collection and storage

**Scrape Targets**:
- Simulation backend (10s interval)
- Monitoring backend (10s interval)
- Self-monitoring

**Metrics Types**:
- **Counter**: Cumulative metrics (e.g., total requests)
- **Gauge**: Point-in-time values (e.g., active users)
- **Histogram**: Distribution of values (e.g., request duration)

#### Grafana

**Purpose**: Metrics visualization and alerting

**Features**:
- Pre-configured dashboards
- Custom query builder
- Alert rules
- Data source integration

## Data Flow

### Chat Interaction Flow

```
1. User sends message via Frontend
   ↓
2. Frontend POSTs to /chat/interact (Simulation Backend)
   ↓
3. ChatMemoryBridge processes interaction
   ↓
4. Civilization resources updated
   ↓
5. Event logged to audit logs
   ↓
6. WebSocket event emitted to Frontend
   ↓
7. POST to /api/chat/save (Monitoring Backend)
   ↓
8. Chat saved to MongoDB
   ↓
9. Recent chat cached in Redis
   ↓
10. Metrics updated in Prometheus
    ↓
11. Frontend receives real-time update
    ↓
12. Charts and stats refreshed
```

### Simulation Cycle Flow

```
1. User clicks "Run Cycles" button
   ↓
2. Frontend POSTs to /simulate/<cycles>
   ↓
3. CycleKernel.run_simulation() executes
   ↓
4. For each universe:
   ↓
5. Universe.simulate_cycle() runs
   ↓
6. For each civilization:
   ↓
7. Resources updated (attention decay, compute usage)
   ↓
8. Beliefs drift randomly
   ↓
9. Memory nodes created
   ↓
10. Metrics exported to Prometheus
    ↓
11. State returned to Frontend
    ↓
12. Charts updated with new data
```

### Metrics Collection Flow

```
1. Application exposes /metrics endpoint
   ↓
2. Prometheus scrapes metrics (10-30s interval)
   ↓
3. Metrics stored in Prometheus TSDB
   ↓
4. Grafana queries Prometheus
   ↓
5. Dashboards display visualizations
   ↓
6. Alert rules evaluated
   ↓
7. Notifications sent (if configured)
```

## Deployment Architecture

### Docker Compose Orchestration

**Networks**:
- `cyclekernel-network`: Bridge network for inter-container communication

**Volumes**:
- `mongodb-data`: Persistent MongoDB storage
- `redis-data`: Persistent Redis storage
- `prometheus-data`: Prometheus time-series database
- `grafana-data`: Grafana configuration and dashboards

**Service Dependencies**:
```
frontend → simulation, monitoring
monitoring → mongodb, redis
grafana → prometheus
prometheus → simulation, monitoring
```

### Port Mapping

| Service | Internal Port | External Port | Purpose |
|---------|--------------|---------------|---------|
| Frontend | 80 | 8080 | Web UI |
| Simulation | 5000 | 5000 | Simulation API |
| Monitoring | 3000 | 3000 | Monitoring API |
| MongoDB | 27017 | 27017 | Database |
| Redis | 6379 | 6379 | Cache |
| Prometheus | 9090 | 9090 | Metrics |
| Grafana | 3000 | 3001 | Dashboards |

## Security Considerations

### Application Security

1. **Rate Limiting**: 100 requests per 15 minutes per IP
2. **Helmet.js**: Security headers (XSS, CSRF protection)
3. **CORS**: Configured allowed origins
4. **Input Validation**: Mongoose schema validation
5. **Error Handling**: No sensitive data in error responses

### Network Security

1. **Docker Networks**: Isolated container communication
2. **Port Exposure**: Only necessary ports exposed
3. **Environment Variables**: Sensitive data in env vars
4. **Health Checks**: Automated service monitoring

### Data Security

1. **MongoDB**: No default authentication (add in production)
2. **Redis**: No default authentication (add in production)
3. **Grafana**: Default admin password (change in production)
4. **HTTPS**: Not configured (add reverse proxy in production)

## Scalability Considerations

### Horizontal Scaling

- **Frontend**: Stateless, can be replicated
- **Simulation Backend**: Can run multiple instances with load balancer
- **Monitoring Backend**: Can run multiple instances
- **MongoDB**: Replica sets for high availability
- **Redis**: Cluster mode for distributed caching

### Vertical Scaling

- **Simulation Backend**: CPU-intensive, benefits from more cores
- **MongoDB**: Memory-intensive, benefits from more RAM
- **Prometheus**: Disk I/O intensive, benefits from SSD

### Performance Optimization

1. **Caching Strategy**: Redis for frequently accessed data
2. **Database Indexing**: MongoDB indexes on userId, timestamp
3. **Connection Pooling**: Mongoose and Redis connection pools
4. **Lazy Loading**: Frontend components load on demand
5. **Metrics Aggregation**: Pre-aggregated metrics in Prometheus

## Monitoring and Observability

### Key Metrics

**Simulation Metrics**:
- `simulation_cycles_total`: Total cycles executed
- `active_civilizations`: Current civilization count
- `total_attention`: Aggregate attention resources
- `total_compute`: Aggregate compute resources
- `chat_interactions_total`: Total chat interactions
- `simulation_cycle_duration_seconds`: Cycle execution time

**Monitoring Metrics**:
- `http_request_duration_seconds`: API response time
- `chat_history_total_size`: Database size
- `active_users_total`: Active user count

### Health Checks

All services implement health check endpoints:
- HTTP GET `/health`
- Returns JSON with status and timestamp
- Docker health checks configured with retries

### Logging

- **Simulation**: Python logging to stdout
- **Monitoring**: Morgan HTTP logging
- **Docker**: Centralized log collection via `docker-compose logs`

## Future Enhancements

### Planned Features

1. **Authentication**: User authentication and authorization
2. **WebSocket Scaling**: Redis adapter for Socket.io
3. **API Gateway**: Unified API entry point
4. **Service Mesh**: Istio for advanced traffic management
5. **CI/CD Pipeline**: Automated testing and deployment
6. **Kubernetes**: Container orchestration for production
7. **Distributed Tracing**: OpenTelemetry integration
8. **Advanced Analytics**: Machine learning on simulation data

### Technical Debt

1. Add comprehensive unit tests
2. Implement integration tests
3. Add API documentation (Swagger/OpenAPI)
4. Implement proper error boundaries in React
5. Add database migrations
6. Implement backup and restore procedures

## Conclusion

The CycleKernel-Integrated platform demonstrates a modern, scalable architecture combining simulation, monitoring, and visualization capabilities. The microservices approach allows for independent scaling and deployment of components, while the comprehensive monitoring stack ensures observability and reliability.

For questions or contributions, please refer to the main README.md or open an issue on GitHub.
