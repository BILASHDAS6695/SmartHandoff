resource "google_redis_instance" "cache" {
  name           = "smarthandoff-redis-${var.environment}"
  tier           = "STANDARD_HA" # HA failover within the region
  memory_size_gb = 2
  region         = var.region
  project        = var.project_id

  # Private IP only — accessed via VPC connector from Cloud Run services
  authorized_network = var.vpc_id
  connect_mode       = "PRIVATE_SERVICE_ACCESS"

  redis_version = "REDIS_7_0"
  display_name  = "SmartHandoff Cache (${var.environment})"

  redis_configs = {
    "maxmemory-policy"       = "allkeys-lru" # Evict LRU keys when memory is full
    "notify-keyspace-events" = "Ex"          # Keyspace events for expiry notifications
  }

  maintenance_policy {
    weekly_maintenance_window {
      day = "SUNDAY"
      start_time {
        hours   = 2
        minutes = 0
      }
    }
  }
}
