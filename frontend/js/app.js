// DeadlineRadar frontend boot script.
// The full application shell is implemented in later commits.
fetch("/api/health")
  .then((response) => response.json())
  .then((health) => {
    document.documentElement.dataset.api = health.status;
  })
  .catch(() => {
    document.documentElement.dataset.api = "offline";
  });
