; Custom look of the VerseForge installer (Inno Setup 6.7+): dark like the app, background with the floor grid, the
; logo's diamond. Images made by tools/installer_art.py. Included by VerseForge.iss (and by the preview build).
#ifndef StyleDir
  #define StyleDir "style"
#endif

[Setup]
WizardStyle=modern dark hidebevels includetitlebar
WizardBackColor=#0b131b
WizardBackImageFile={#StyleDir}\back-100.png,{#StyleDir}\back-125.png,{#StyleDir}\back-150.png,{#StyleDir}\back-200.png
WizardImageFile={#StyleDir}\side-100.png,{#StyleDir}\side-125.png,{#StyleDir}\side-150.png,{#StyleDir}\side-200.png
WizardSmallImageFile={#StyleDir}\logo-100.png,{#StyleDir}\logo-125.png,{#StyleDir}\logo-150.png,{#StyleDir}\logo-200.png
DisableWelcomePage=no

[Messages]
WelcomeLabel1=Welcome to VerseForge
WelcomeLabel2=This will install [name/ver] on your computer.%n%nExplore every ship, weapon and armour set of Star Citizen in 3D, straight from your own game files, and export them for Blender, renders or 3D printing.%n%nUnofficial fan project, not affiliated with Cloud Imperium Games.
FinishedHeadingLabel=VerseForge is ready
FinishedLabel=[name] is installed. It finds Star Citizen by itself; if your game is somewhere else, set the path in Settings (gear icon, top right).
FinishedLabelNoIcons=[name] is installed. It finds Star Citizen by itself; if your game is somewhere else, set the path in Settings (gear icon, top right).
