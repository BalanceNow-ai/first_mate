allprojects {
    repositories {
        google()
        mavenCentral()
    }
}

val newBuildDir: Directory =
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}
subprojects {
    project.evaluationDependsOn(":app")
}
subprojects {
    // stripe_android's lint checks pull Stripe's issuing push-provisioning module, which
    // needs Google's private play-services-tapandpay SDK (not in any public repository).
    // Helm does not use card push provisioning; exclude it from lint classpaths only.
    configurations.configureEach {
        if (name.contains("LintChecks", ignoreCase = true)) {
            exclude(group = "com.stripe", module = "stripe-android-issuing-push-provisioning")
        }
    }
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
