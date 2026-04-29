const express = require("express");
const cors = require("cors");
const app = express();

app.use(cors());
app.use(express.json());

let tasks = [];

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

app.listen(3000, () => console.log("Server running on port 3000"));