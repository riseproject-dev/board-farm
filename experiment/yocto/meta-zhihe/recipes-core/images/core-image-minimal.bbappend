# Ensure /init symlink points to /sbin/init for in-memory initrd netboot
ROOTFS_POSTPROCESS_COMMAND += "create_init_symlink; "

create_init_symlink() {
    if [ ! -e ${IMAGE_ROOTFS}/init ]; then
        ln -sf /sbin/init ${IMAGE_ROOTFS}/init
    fi
}
