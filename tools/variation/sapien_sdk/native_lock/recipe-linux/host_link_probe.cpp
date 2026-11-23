#include <PxPhysicsAPI.h>

extern "C" unsigned dexarena_physx_native_lock_sync_patch_version();

int main() {
    physx::PxDefaultAllocator allocator;
    physx::PxDefaultErrorCallback errors;
    auto *foundation = PxCreateFoundation(PX_PHYSICS_VERSION, allocator, errors);
    if (!foundation) {
        return 1;
    }
    auto *physics = PxCreatePhysics(PX_PHYSICS_VERSION, *foundation, physx::PxTolerancesScale());
    if (!physics) {
        foundation->release();
        return 2;
    }
    auto *body = physics->createRigidDynamic(physx::PxTransform(physx::PxIdentity));
    if (!body) {
        physics->release();
        foundation->release();
        return 3;
    }
    const auto flag = physx::PxRigidDynamicLockFlag::eLOCK_LINEAR_X;
    body->setRigidDynamicLockFlags(flag);
    const bool set = body->getRigidDynamicLockFlags().isSet(flag);
    body->setRigidDynamicLockFlags(physx::PxRigidDynamicLockFlags{});
    const bool cleared = !body->getRigidDynamicLockFlags().isSet(flag);
    body->release();
    physics->release();
    foundation->release();
    return set && cleared && dexarena_physx_native_lock_sync_patch_version() == 1 ? 0 : 4;
}
