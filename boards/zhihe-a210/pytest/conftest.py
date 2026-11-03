import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--pool",
        action="store",
        default="a210-yocto",
        help="Labgrid pool tag to dynamically reserve an available board from (default: a210-yocto)",
    )
    parser.addoption(
        "--place",
        action="store",
        default="",
        help="Optional explicit Labgrid place override (if empty, dynamically reserves from --pool)",
    )
    parser.addoption(
        "--tftp-dir",
        action="store",
        required=True,
        help="Relative directory under /var/lib/tftpboot containing Image, a210-dev.dtb, and rootfs.cpio.gz",
    )
    parser.addoption(
        "--serial-log",
        action="store",
        default="yocto_serial_boot.log",
        help="Path to write the full captured UART boot and teardown transcript",
    )
    parser.addoption(
        "--expected-kernel-prefix",
        action="store",
        default="",
        help="Optional expected kernel release prefix (e.g. '7.2.12')",
    )


@pytest.fixture
def pool_name(request):
    return request.config.getoption("--pool")


@pytest.fixture
def place_name(request):
    return request.config.getoption("--place")


@pytest.fixture
def tftp_dir(request):
    return request.config.getoption("--tftp-dir").strip("/")


@pytest.fixture
def serial_log_path(request):
    return request.config.getoption("--serial-log")


@pytest.fixture
def expected_kernel_prefix(request):
    return request.config.getoption("--expected-kernel-prefix")
