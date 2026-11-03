variable "name" {
  description = "Name prefix for the roles."
  type        = string
}

variable "pod_roles" {
  description = "Roles to create, by short name: the namespace and service account that will use it, and its permissions as a JSON policy."
  type = map(object({
    namespace       = string
    service_account = string
    policy_json     = string
  }))

  validation {
    condition     = alltrue([for r in values(var.pod_roles) : can(jsondecode(r.policy_json))])
    error_message = "pod_roles: every policy_json must be valid JSON."
  }

  validation {
    condition = alltrue(flatten([
      for r in values(var.pod_roles) : [
        for s in jsondecode(r.policy_json).Statement : !(s.Effect == "Allow" && contains(flatten([s.Action]), "*"))
      ]
    ]))
    error_message = "pod_roles: no statement may allow every action (\"*\")."
  }
}

variable "tags" {
  description = "Tags added to every resource."
  type        = map(string)
  default     = {}
}
