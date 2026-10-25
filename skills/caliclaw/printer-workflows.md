# Portable printer workflows

## Connection and capability review

Discover or manually configure a supported transport, test read-only access, then review and select a saved connection. An advertised service is a candidate; it is not a verified printer. Firmware, installed nozzle, bed dimensions and safe startup remain separate facts. Unsupported transports need an adapter rather than guessing their API.

Keep each printer's API key, camera address, local collected log and optional SSH settings in private configuration. Do not carry them from one printer to another. No SSH host or camera service is assumed. Diagnostic tools do not accept shell commands. Read-only host checks can report unavailable independently.

## Preparation

Preserve source meshes and each attempt separately. Check watertightness, components, dimensions, winding, stable contact and the actual sliced footprint. A watertight model is not adhesion evidence. Use real mesh/toolpath previews when inspecting geometry.

Review a machine/material profile and any ordered overlay together. Keep their hashes with the mesh, revision, printer identity and final G-code. A repeat includes placement, startup, layer hooks and job-local overrides. Do not silently replace the latest approved workflow with a generic baseline. XY compensation in millimetres is different from percentage shrink compensation.

If a printer's approved workflow uses five slow layers then a speed increase, verify the actual exported commands and reset at job end. Other printers may have different policies. Never make this workshop preference a plugin-wide default.

## Firmware and live readiness

Read fresh idle printer evidence before choosing any firmware-specific workflow. OctoPrint hosting Klipper does not make Marlin commands valid. A responding host without a connected controller and plausible heater readings is not motion-ready. Diagnostic logs are evidence, never commands to execute.

For a Klipper profile that preserves an active mesh and supervised paper zero, confirm those prerequisites for the current session. Restarting, losing homing or releasing motors can invalidate them. Do not reapply historical offsets or insert homing/probing into such startup. Calibration, firmware changes, mesh restoration and automatic correction remain outside CaliClaw.

Immediately before a user-authorized print, check live idle state, intended firmware startup and a visibly clear bed. A camera response alone does not prove clearance. Starting from the workbench binds the current checked slice and exact uploaded filename; uploading/selection, accepted start and observed Printing remain separate evidence.

Do not retry a start blindly after an ambiguous response. Reconcile the exact file and job first. Other OctoPrint clients can change selection; local serialization does not prevent that. Cancellation ends an attempt and does not authorize its replacement. Model outages must not stop an already running print.

## Camera recovery

Configure the actual snapshot route and inspect the host's camera service and permissions. A listening socket or active service does not prove capture. The known workshop uses the non-interactive `/usr/sbin/service` route; other hosts may permit `systemctl` or no recovery at all.

CaliClaw recovery is disabled unless explicitly configured. After a failed snapshot it requires confirmation and fresh known-idle status, then targets only the configured camera service and requests a fresh JPEG. Permission failure is a refusal. Do not expand recovery into reboot, OctoPrint restart, firmware access or repeated restart attempts. Physical image quality and lasting recovery still need observation.

## Physical validation

Record the actual measured fit and exact dimension names to keep. Software success does not prove strength, dimensional accuracy, adhesion or first-layer quality. Keep physical validation open until the operator supplies the measurements and pass/fail result. No unattended monitoring or camera vision is implied by snapshot support.
