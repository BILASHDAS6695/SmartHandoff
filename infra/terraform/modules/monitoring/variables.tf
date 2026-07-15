variable "project_id"         { type = string }
variable "environment"         { type = string }
variable "api_domain"          { type = string }
variable "oncall_email"        { type = string }
variable "slack_alert_channel" { type = string  default = "#smarthandoff-alerts" }
