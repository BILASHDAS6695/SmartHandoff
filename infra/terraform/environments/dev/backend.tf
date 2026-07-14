terraform {
  backend "gcs" {
    bucket  = "smarthandoff-tf-state-dev"
    prefix  = "terraform/state"
  }
}
