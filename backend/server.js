const express = require("express");
const cors = require("cors");
const app = express();

const PORT = process.env.PORT || 5000;
const HOST = "0.0.0.0";

app.use(cors());
app.use(express.json());

let tasks = [];

app.get("/", (req, res) => {
  res.json({
    name: "lifeos-agent backend",
    status: "ok",
    endpoints: {
      "GET /tasks": "list tasks",
      "POST /tasks": "add task",
      "PUT /tasks/:id": "update task"
    },
    tasksCount: tasks.length
  });
});

app.get("/tasks", (req, res) => {
  res.json(tasks);
});

app.post("/tasks", (req, res) => {
  tasks.push(req.body);
  res.send("Task added");
});

app.put("/tasks/:id", (req, res) => {
  tasks[req.params.id] = req.body;
  res.send("Updated");
});

app.listen(PORT, HOST, () =>
  console.log(`Server running on http://${HOST}:${PORT}`)
);
