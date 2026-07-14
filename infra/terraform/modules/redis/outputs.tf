output "redis_host" {
  description = "Private IP address of the Redis instance (set as REDIS_HOST env var in Cloud Run)"
  value       = google_redis_instance.cache.host
  sensitive   = true
}

output "redis_port" {
  description = "Port of the Redis instance (default: 6379)"
  value       = google_redis_instance.cache.port
}
