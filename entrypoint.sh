#!/bin/bash
set -e

CF_DIR="$HOME/cuttlefish"
IMG_DIR="${CF_DIR}/images"
RUN_DIR="${CF_DIR}/run"

mkdir -p "${IMG_DIR}" "${RUN_DIR}"

get_latest_build() {
    local channel="${1:-stable}"
    curl -fsSL "https://releases.grapheneos.org/${channel}" 2>/dev/null | head -1
}

list_available_images() {
    local build_id="$1"
    local base_url="https://releases.grapheneos.org/cuttlefish-${build_id}"
    echo "Available image variants:"
    curl -fsSL "${base_url}/" 2>/dev/null | \
        grep -oP 'href="[^"]*\.tar\.xz"' | \
        sed 's/href="//;s/"//' || echo "(unable to list)"
}

download_image() {
    local build_id="$1"
    if [ -z "$build_id" ]; then
        echo "Fetching latest stable build..."
        build_id=$(get_latest_build "stable")
    fi

    echo "Build ID: ${build_id}"
    local dest="${IMG_DIR}/${build_id}"
    mkdir -p "${dest}"

    if [ -f "${dest}/.downloaded" ]; then
        echo "Image already downloaded: ${build_id}"
        return 0
    fi

    local base_url="https://releases.grapheneos.org/cuttlefish-${build_id}"
    cd "${dest}"

    # List available files
    echo "Checking available images at ${base_url}..."
    local file_list
    file_list=$(curl -fsSL "${base_url}/" 2>/dev/null | \
        grep -oP 'href="[^"]*\.(tar\.xz|img|zip)"' | \
        sed 's/href="//;s/"//' || true)

    if [ -z "$file_list" ]; then
        echo "No files found at ${base_url}"
        echo "Trying alternative image format..."
        # Try the standard cuttlefish image naming
        file_list="cuttlefish-img-${build_id}.tar.xz"
    fi

    echo "Files to download:"
    echo "${file_list}"

    # Download image archive
    for file in ${file_list}; do
        if [ ! -f "${file}" ]; then
            echo "Downloading ${file}..."
            wget --progress=bar:force -O "${file}" "${base_url}/${file}" 2>&1 || \
                echo "  Failed to download ${file}"
        fi
    done

    # Extract archives
    for archive in *.tar.xz; do
        [ -f "${archive}" ] || continue
        echo "Extracting ${archive}..."
        tar xf "${archive}" --checkpoint=.100
        echo ""
    done

    for archive in *.zip; do
        [ -f "${archive}" ] || continue
        echo "Extracting ${archive}..."
        unzip -o "${archive}"
    done

    # Also extract nested archives (e.g. from target_files zip)
    for archive in "${dest}"/IMAGES/*.tar.xz "${dest}"/IMAGES/*.xz; do
        [ -f "${archive}" ] || continue
        echo "Extracting nested ${archive}..."
        cd "${dest}"
        tar xf "${archive}" --checkpoint=.100 2>/dev/null || true
    done

    touch "${dest}/.downloaded"

    echo ""
    echo "=== Image contents ==="
    find "${dest}" -maxdepth 3 -name "*.img" -o -name "kernel*" -o -name "ramdisk*" | head -20
    echo "====================="

    echo "Download complete: ${build_id}"
}

find_kernel() {
    local dir="$1"
    find "${dir}" -maxdepth 4 \( -name "bzImage" -o -name "vmlinux" -o -name "kernel" -o -name "kernel-*" \) 2>/dev/null | head -1
}

find_ramdisk() {
    local dir="$1"
    find "${dir}" -maxdepth 4 \( -name "ramdisk.img" -o -name "ramdisk*" -o -name "initramfs*" \) 2>/dev/null | head -1
}

find_system_img() {
    local dir="$1"
    find "${dir}" -maxdepth 4 -name "system.img" 2>/dev/null | head -1
}

find_vendor_img() {
    local dir="$1"
    find "${dir}" -maxdepth 4 -name "vendor.img" 2>/dev/null | head -1
}

find_userdata_img() {
    local dir="$1"
    find "${dir}" -maxdepth 4 \( -name "userdata.img" -o -name "disk.img" \) 2>/dev/null | head -1
}

find_vbmeta_img() {
    local dir="$1"
    find "${dir}" -maxdepth 4 -name "vbmeta.img" 2>/dev/null | head -1
}

run_qemu() {
    local build_id="$1"
    if [ -z "$build_id" ]; then
        build_id=$(get_latest_build "stable")
    fi

    local dest="${IMG_DIR}/${build_id}"
    if [ ! -f "${dest}/.downloaded" ]; then
        download_image "${build_id}"
    fi

    echo "Searching for boot images in ${dest}..."

    local kernel=$(find_kernel "${dest}")
    local ramdisk=$(find_ramdisk "${dest}")
    local system_img=$(find_system_img "${dest}")
    local vendor_img=$(find_vendor_img "${dest}")
    local userdata_img=$(find_userdata_img "${dest}")

    echo "Found:"
    echo "  Kernel:    ${kernel:-NOT FOUND}"
    echo "  Ramdisk:   ${ramdisk:-NOT FOUND}"
    echo "  System:    ${system_img:-NOT FOUND}"
    echo "  Vendor:    ${vendor_img:-NOT FOUND}"
    echo "  Userdata:  ${userdata_img:-NOT FOUND}"

    if [ -z "${system_img}" ]; then
        echo "ERROR: No system.img found. Image download may have failed."
        echo "Directory contents:"
        find "${dest}" -maxdepth 3 -type f | head -30
        return 1
    fi

    # Create a composite disk if we have separate images
    local disk_img="${RUN_DIR}/disk-${build_id}.img"
    if [ ! -f "${disk_img}" ] && [ -n "${userdata_img}" ]; then
        echo "Creating combined disk image..."
        cp "${userdata_img}" "${disk_img}"
    fi

    # Build QEMU command
    local qemu_args=(
        -m 3072
        -smp 2
        -machine q35
        -cpu qemu64
        -nographic
        -no-reboot
        -serial mon:stdio
        -audiodev none,id=snd0
    )

    # Networking - expose adb and web UI
    qemu_args+=(
        -netdev user,id=net0,hostfwd=tcp::5555-:5555,hostfwd=tcp::6520-:5555,hostfwd=tcp::8443-:8443,hostfwd=tcp::8444-:8444
        -device virtio-net-pci,netdev=net0
    )

    # Disk images
    if [ -f "${system_img}" ]; then
        qemu_args+=(-drive file="${system_img}",format=raw,if=virtio,readonly=on)
    fi
    if [ -n "${vendor_img}" ] && [ -f "${vendor_img}" ]; then
        qemu_args+=(-drive file="${vendor_img}",format=raw,if=virtio,readonly=on)
    fi
    if [ -f "${disk_img}" ]; then
        qemu_args+=(-drive file="${disk_img}",format=raw,if=virtio)
    fi

    # Kernel boot if available
    if [ -n "${kernel}" ] && [ -f "${kernel}" ]; then
        qemu_args+=(-kernel "${kernel}")
        if [ -n "${ramdisk}" ] && [ -f "${ramdisk}" ]; then
            qemu_args+=(-initrd "${ramdisk}")
        fi
        local cmdline="console=ttyS0 androidboot.hardware=ranchu qemu=1"
        cmdline+=" androidboot.selinux=permissive"
        cmdline+=" androidboot.verifiedbootstate=orange"
        cmdline+=" loglevel=4"
        qemu_args+=(-append "${cmdline}")
    fi

    echo ""
    echo "Starting QEMU (software emulation)..."
    echo "NOTE: Without KVM, Android will boot VERY slowly (10-20 min)."
    echo "Connect with: adb connect localhost:6520"
    echo ""

    # Save pid file
    echo $$ > "${RUN_DIR}/vm.pid"

    exec qemu-system-x86_64 "${qemu_args[@]}" "$@"
}

run_with_cvd() {
    local build_id="$1"
    if [ -z "$build_id" ]; then
        build_id=$(get_latest_build "stable")
    fi

    local dest="${IMG_DIR}/${build_id}"
    if [ ! -f "${dest}/.downloaded" ]; then
        download_image "${build_id}"
    fi

    echo "Starting cuttlefish with cvd (no hypervisor / software emulation)..."
    echo "Build: ${build_id}"
    echo ""

    export HOME="$HOME"
    export CUTTLEFISH_INSTANCE="1"

    if command -v launch_cvd >/dev/null 2>&1; then
        cd "${dest}"
        HOME="$HOME" launch_cvd \
            --daemon \
            --no_hypervisor \
            --report_anonymous_usage_stats=n \
            --console \
            --gpu_mode=auto \
            --cpus 2 \
            --memory_mb 2048 \
            -image_dir_path="${dest}" \
            "$@"

        echo ""
        echo "VM launched!"
        echo "  ADB:   adb connect localhost:6520"
        echo "  Web:   http://localhost:8443"
        echo ""
        tail -f /dev/null
    elif command -v cvd >/dev/null 2>&1; then
        cvd start \
            --no_hypervisor \
            --report_anonymous_usage_stats=n \
            --console \
            --gpu_mode=auto \
            --cpus 2 \
            --memory_mb 2048 \
            "$@"

        echo ""
        echo "VM launched!"
        echo "  ADB:   adb connect localhost:6520"
        echo "  Web:   http://localhost:8443"
        echo ""
        tail -f /dev/null
    else
        echo "cvd/launch_cvd not found. Falling back to direct QEMU..."
        run_qemu "${build_id}"
    fi
}

case "${1:-help}" in
    download)
        download_image "$2"
        ;;
    run)
        shift
        run_with_cvd "$@"
        ;;
    qemu)
        shift
        run_qemu "$@"
        ;;
    list)
        local_build_id="${2:-$(get_latest_build stable)}"
        list_available_images "${local_build_id}"
        ;;
    latest)
        get_latest_build "${2:-stable}"
        ;;
    shell)
        exec /bin/bash
        ;;
    help|*)
        echo "GrapheneOS Cuttlefish VM"
        echo ""
        echo "Commands:"
        echo "  download [build_id]    Download GrapheneOS cuttlefish image"
        echo "  run [build_id]         Start VM (auto-downloads if needed)"
        echo "  qemu [build_id]        Start VM with direct QEMU (fallback)"
        echo "  list [build_id]        List available image files"
        echo "  latest [channel]       Show latest build ID (stable/beta)"
        echo "  shell                  Interactive shell"
        echo ""
        echo "Examples:"
        echo "  # Download and run latest stable"
        echo "  docker run ... run"
        echo ""
        echo "  # Run specific build"
        echo "  docker run ... run 2026010100"
        ;;
esac
