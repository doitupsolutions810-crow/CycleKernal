/**
 * CycleKernel Monitoring Server
 * Node.js/Express server with MongoDB, Redis, and Prometheus integration
 */

const express = require('express');
const mongoose = require('mongoose');
const redis = require('redis');
const promClient = require('prom-client');
const cors = require('cors');
const morgan = require('morgan');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(helmet());
app.use(cors());
app.use(express.json());
app.use(morgan('combined'));

// Rate limiting
const limiter = rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 100 // limit each IP to 100 requests per windowMs
});
app.use('/api/', limiter);

// Prometheus metrics setup
const register = new promClient.Registry();
promClient.collectDefaultMetrics({ register });

// Custom metrics
const httpRequestDuration = new promClient.Histogram({
  name: 'http_request_duration_seconds',
  help: 'Duration of HTTP requests in seconds',
  labelNames: ['method', 'route', 'status_code'],
  registers: [register]
});

const chatHistorySize = new promClient.Gauge({
  name: 'chat_history_total_size',
  help: 'Total size of chat history in database',
  registers: [register]
});

const activeUsers = new promClient.Gauge({
  name: 'active_users_total',
  help: 'Total number of active users',
  registers: [register]
});

// MongoDB connection
const MONGODB_URI = process.env.MONGODB_URI || 'mongodb://mongodb:27017/cyclekernel';
mongoose.connect(MONGODB_URI, {
  useNewUrlParser: true,
  useUnifiedTopology: true
})
.then(() => console.log('✅ Connected to MongoDB'))
.catch(err => console.error('❌ MongoDB connection error:', err));

// MongoDB Schemas
const ChatHistorySchema = new mongoose.Schema({
  userId: { type: String, required: true, index: true },
  civId: String,
  message: String,
  response: String,
  timestamp: { type: Date, default: Date.now },
  metadata: {
    attention: Number,
    compute: Number,
    memoryNodes: Number,
    belief: {
      truth: Number,
      deception: Number
    }
  }
});

const SimulationSnapshotSchema = new mongoose.Schema({
  universeId: String,
  cycleCount: Number,
  timestamp: { type: Date, default: Date.now },
  civilizations: mongoose.Schema.Types.Mixed,
  factions: mongoose.Schema.Types.Mixed,
  metrics: {
    totalAttention: Number,
    totalCompute: Number,
    totalMemoryNodes: Number
  }
});

const ChatHistory = mongoose.model('ChatHistory', ChatHistorySchema);
const SimulationSnapshot = mongoose.model('SimulationSnapshot', SimulationSnapshotSchema);

// Redis connection
const redisClient = redis.createClient({
  url: process.env.REDIS_URL || 'redis://redis:6379'
});

redisClient.on('error', (err) => console.error('❌ Redis error:', err));
redisClient.on('connect', () => console.log('✅ Connected to Redis'));

(async () => {
  await redisClient.connect();
})();

// Middleware to track request duration
app.use((req, res, next) => {
  const start = Date.now();
  res.on('finish', () => {
    const duration = (Date.now() - start) / 1000;
    httpRequestDuration.labels(req.method, req.route?.path || req.path, res.statusCode).observe(duration);
  });
  next();
});

// ============ API ROUTES ============

// Health check
app.get('/health', (req, res) => {
  res.json({
    status: 'healthy',
    timestamp: new Date().toISOString(),
    services: {
      mongodb: mongoose.connection.readyState === 1 ? 'connected' : 'disconnected',
      redis: redisClient.isOpen ? 'connected' : 'disconnected'
    }
  });
});

// Prometheus metrics endpoint
app.get('/metrics', async (req, res) => {
  res.set('Content-Type', register.contentType);
  res.end(await register.metrics());
});

// Save chat interaction to MongoDB
app.post('/api/chat/save', async (req, res) => {
  try {
    const { userId, civId, message, response, metadata } = req.body;
    
    const chatEntry = new ChatHistory({
      userId,
      civId,
      message,
      response,
      metadata
    });
    
    await chatEntry.save();
    
    // Update metrics
    const totalChats = await ChatHistory.countDocuments();
    chatHistorySize.set(totalChats);
    
    // Cache recent chat in Redis
    await redisClient.setEx(
      `chat:${userId}:latest`,
      3600, // 1 hour TTL
      JSON.stringify({ message, response, timestamp: new Date() })
    );
    
    res.json({ status: 'success', id: chatEntry._id });
  } catch (error) {
    console.error('Error saving chat:', error);
    res.status(500).json({ status: 'error', message: error.message });
  }
});

// Get chat history for a user
app.get('/api/chat/history/:userId', async (req, res) => {
  try {
    const { userId } = req.params;
    const limit = parseInt(req.query.limit) || 50;
    
    // Try Redis cache first
    const cachedHistory = await redisClient.get(`chat:${userId}:history`);
    if (cachedHistory) {
      return res.json({ status: 'success', source: 'cache', data: JSON.parse(cachedHistory) });
    }
    
    // Fetch from MongoDB
    const history = await ChatHistory.find({ userId })
      .sort({ timestamp: -1 })
      .limit(limit)
      .lean();
    
    // Cache for 5 minutes
    await redisClient.setEx(
      `chat:${userId}:history`,
      300,
      JSON.stringify(history)
    );
    
    res.json({ status: 'success', source: 'database', data: history });
  } catch (error) {
    console.error('Error fetching chat history:', error);
    res.status(500).json({ status: 'error', message: error.message });
  }
});

// Save simulation snapshot
app.post('/api/simulation/snapshot', async (req, res) => {
  try {
    const { universeId, cycleCount, civilizations, factions, metrics } = req.body;
    
    const snapshot = new SimulationSnapshot({
      universeId,
      cycleCount,
      civilizations,
      factions,
      metrics
    });
    
    await snapshot.save();
    
    res.json({ status: 'success', id: snapshot._id });
  } catch (error) {
    console.error('Error saving snapshot:', error);
    res.status(500).json({ status: 'error', message: error.message });
  }
});

// Get simulation snapshots
app.get('/api/simulation/snapshots/:universeId', async (req, res) => {
  try {
    const { universeId } = req.params;
    const limit = parseInt(req.query.limit) || 100;
    
    const snapshots = await SimulationSnapshot.find({ universeId })
      .sort({ timestamp: -1 })
      .limit(limit)
      .lean();
    
    res.json({ status: 'success', data: snapshots });
  } catch (error) {
    console.error('Error fetching snapshots:', error);
    res.status(500).json({ status: 'error', message: error.message });
  }
});

// Get active users count
app.get('/api/users/active', async (req, res) => {
  try {
    const timeWindow = 24 * 60 * 60 * 1000; // 24 hours
    const since = new Date(Date.now() - timeWindow);
    
    const activeUsersList = await ChatHistory.distinct('userId', {
      timestamp: { $gte: since }
    });
    
    const count = activeUsersList.length;
    activeUsers.set(count);
    
    res.json({ status: 'success', activeUsers: count, timeWindow: '24h' });
  } catch (error) {
    console.error('Error fetching active users:', error);
    res.status(500).json({ status: 'error', message: error.message });
  }
});

// Get analytics dashboard data
app.get('/api/analytics/dashboard', async (req, res) => {
  try {
    const totalChats = await ChatHistory.countDocuments();
    const totalSnapshots = await SimulationSnapshot.countDocuments();
    
    const recentChats = await ChatHistory.find()
      .sort({ timestamp: -1 })
      .limit(10)
      .lean();
    
    const recentSnapshot = await SimulationSnapshot.findOne()
      .sort({ timestamp: -1 })
      .lean();
    
    res.json({
      status: 'success',
      data: {
        totalChats,
        totalSnapshots,
        recentChats,
        recentSnapshot
      }
    });
  } catch (error) {
    console.error('Error fetching dashboard data:', error);
    res.status(500).json({ status: 'error', message: error.message });
  }
});

// Error handling middleware
app.use((err, req, res, next) => {
  console.error('Unhandled error:', err);
  res.status(500).json({
    status: 'error',
    message: 'Internal server error',
    error: process.env.NODE_ENV === 'development' ? err.message : undefined
  });
});

// 404 handler
app.use((req, res) => {
  res.status(404).json({
    status: 'error',
    message: 'Route not found'
  });
});

// Start server
app.listen(PORT, () => {
  console.log(`🚀 CycleKernel Monitoring Server running on port ${PORT}`);
  console.log(`📊 Metrics available at http://localhost:${PORT}/metrics`);
  console.log(`💚 Health check at http://localhost:${PORT}/health`);
});

// Graceful shutdown
process.on('SIGTERM', async () => {
  console.log('SIGTERM received, shutting down gracefully...');
  await mongoose.connection.close();
  await redisClient.quit();
  process.exit(0);
});
