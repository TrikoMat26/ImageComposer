import sys
import os
import cv2
import numpy as np
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QGraphicsScene, QGraphicsView,
    QGraphicsPixmapItem, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout, QHBoxLayout, QWidget, QLabel, QToolBar, QStatusBar,
    QDockWidget, QGraphicsItem, QSizePolicy, QCheckBox, QDoubleSpinBox,
    QFormLayout, QGroupBox, QGraphicsSceneMouseEvent # << AJOUTER ICI
)
# MODIFICATION ICI: Ajout de QIcon (et QPainter, QSize étaient déjà là)
from PySide6.QtGui import (
    QPixmap, QImage, QPen, QColor, QTransform, QAction, QKeySequence,
    QPainter, QIcon
)
from PySide6.QtCore import (
    Qt, QRectF, QPointF, Signal, QSize, QItemSelectionModel
)

# --- Constantes ---
MAX_IMAGES = 6
MIN_IMAGES = 2
THUMBNAIL_SIZE = 150
STEP_QUICK_MOVE = 10
STEP_PRECISE_MOVE = 1
STEP_QUICK_SCALE = 0.1
STEP_PRECISE_SCALE = 0.01
STEP_QUICK_ROTATE = 15
STEP_PRECISE_ROTATE = 1

class DraggableResizablePixmapItem(QGraphicsPixmapItem):
    # itemSelected = Signal(object) # Supprimé, on utilise scene.selectionChanged

    def __init__(self, pixmap, filename, original_cv_image):
        super().__init__(pixmap)
        self.filename = filename
        self.original_cv_image = original_cv_image
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable | # Déjà géré par QGraphicsItem
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True) # Pour le curseur
        self.setTransformOriginPoint(self.boundingRect().center()) # Important pour la rotation/échelle
        self.setOpacity(1.0)

        self._is_active = False # Pour le contour

        # Variables pour la manipulation personnalisée à la souris
        self.mouse_press_pos = QPointF()
        self.mouse_press_item_scale = 1.0
        self.mouse_press_item_rotation = 0.0
        self.current_manipulation_mode = None # 'scale', 'rotate', ou None

        # Pour afficher un curseur différent lors du survol si on veut affiner
        # self.setCursor(Qt.CursorShape.SizeAllCursor) # Curseur de déplacement par défaut

    def set_active(self, active):
        self._is_active = active
        self.update()

    def set_interactive_opacity(self, enable):
        if enable:
            self.setOpacity(0.5)
        else:
            self.setOpacity(1.0)

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        if self.isSelected(): # Ou self._is_active
            pen = QPen(QColor("red"), 3, Qt.SolidLine)
            painter.setPen(pen)
            brect = self.boundingRect()
            painter.drawRect(brect.adjusted(-2, -2, 2, 2))

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent): # Type hint pour autocomplétion
        # Préparer pour la manipulation personnalisée ou le déplacement standard
        if event.button() == Qt.MouseButton.LeftButton:
            self.mouse_press_pos = event.scenePos() # Position de la souris dans la scène
            self.mouse_press_item_scale = self.scale()
            self.mouse_press_item_rotation = self.rotation()

            modifiers = QApplication.keyboardModifiers() # Récupérer les modificateurs globaux

            if modifiers == Qt.KeyboardModifier.ShiftModifier:
                self.current_manipulation_mode = 'scale'
                self.setCursor(Qt.CursorShape.SizeFDiagCursor) # Ou un autre curseur d'échelle
                event.accept() # Indiquer que nous gérons cet événement
                return # Empêcher le déplacement standard de QGraphicsItem
            elif modifiers == Qt.KeyboardModifier.ControlModifier:
                self.current_manipulation_mode = 'rotate'
                self.setCursor(Qt.CursorShape.CrossCursor) # Ou un curseur de rotation
                event.accept()
                return

        # Si pas de modificateur spécial pour nos actions, laisser QGraphicsItem gérer le déplacement
        self.current_manipulation_mode = None
        super().mousePressEvent(event) # Gère ItemIsMovable et la sélection
        # La gestion du Z-order peut rester ici si on veut que chaque clic amène au premier plan
        if self.scene():
            other_pixmap_items_z = [
                itm.zValue() for itm in self.scene().items()
                if isinstance(itm, DraggableResizablePixmapItem) and itm is not self
            ]
            new_z = (max(other_pixmap_items_z) + 1) if other_pixmap_items_z else 1.0
            self.setZValue(new_z)
            # print(f"[DEBUG] Item {self.filename}: mousePress, Z mis à {new_z}")


    # Dans la classe DraggableResizablePixmapItem

    def mouseMoveEvent(self, event: 'QGraphicsSceneMouseEvent'):
        if self.current_manipulation_mode and (event.buttons() & Qt.MouseButton.LeftButton):
            current_mouse_pos = event.scenePos()
            delta_pos = current_mouse_pos - self.mouse_press_pos

            main_window = None
            if self.scene():
                view_widget = self.scene().parent()
                if view_widget and hasattr(view_widget, 'parent') and isinstance(view_widget.parent(), MainWindow):
                    main_window = view_widget.parent()

            # Déterminer la sensibilité en fonction du mode précis de la MainWindow
            is_precise_mouse_mode = False
            if main_window and hasattr(main_window, 'is_precise_mode'):
                is_precise_mouse_mode = main_window.is_precise_mode
                # print(f"[DEBUG] Mouse precise mode: {is_precise_mouse_mode}") # Pour débogage

            if self.current_manipulation_mode == 'scale':
                if is_precise_mouse_mode:
                    scale_sensitivity = 0.0001 # Sensibilité précise
                else:
                    scale_sensitivity = 0.0005 # Sensibilité rapide
                # print(f"[DEBUG] Scale sensitivity: {scale_sensitivity}") # Pour débogage


                scale_change = -delta_pos.y() * scale_sensitivity
                new_scale = self.mouse_press_item_scale + scale_change
                new_scale = max(0.05, new_scale)
                self.setScale(new_scale)

                if main_window and hasattr(main_window, '_on_item_manipulated'):
                    main_window._on_item_manipulated(self) # Mise à jour des spinbox (si souhaité en temps réel)

                event.accept()
                return

            elif self.current_manipulation_mode == 'rotate':
                center_point = self.mapToScene(self.transformOriginPoint()) # Point central de l'item dans la scène

                # Vecteur initial depuis le centre vers la position de pression de la souris
                vec_initial = self.mouse_press_pos - center_point
                # Vecteur actuel depuis le centre vers la position actuelle de la souris
                vec_current = current_mouse_pos - center_point

                # Angle de chaque vecteur par rapport à l'horizontale (atan2 donne de -pi à pi)
                angle_initial_rad = np.arctan2(vec_initial.y(), vec_initial.x())
                angle_current_rad = np.arctan2(vec_current.y(), vec_current.x())

                # Différence d'angle en radians
                delta_angle_rad = angle_current_rad - angle_initial_rad

                # Convertir en degrés
                delta_angle_deg = np.degrees(delta_angle_rad)

                # Appliquer à la rotation initiale de l'item
                new_rotation = self.mouse_press_item_rotation + delta_angle_deg

                # Ici, la "sensibilité" est intrinsèque à la distance du curseur au centre.
                # Si vous voulez toujours un facteur de sensibilité global :
                # sensitivity_factor = 0.5 # Si 1.0, rotation directe. < 1.0 pour plus lent.
                # new_rotation = self.mouse_press_item_rotation + (delta_angle_deg * sensitivity_factor)

                self.setRotation(new_rotation)

                if main_window and hasattr(main_window, '_on_item_manipulated'):
                    main_window._on_item_manipulated(self) # Mise à jour des spinbox (si souhaité en temps réel)

                event.accept()
                return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        if self.current_manipulation_mode:
            mode_was = self.current_manipulation_mode
            self.current_manipulation_mode = None
            self.unsetCursor()

            # Informer la MainWindow que la manipulation est terminée
            main_window = None
            if self.scene():
                view = self.scene().parent() 
                if view and hasattr(view, 'parent') and isinstance(view.parent(), MainWindow):
                    main_window = view.parent()
            
            if main_window and hasattr(main_window, '_on_item_manipulated'):
                print(f"[DEBUG] Item {self.filename}: mouseRelease, mode {mode_was}, notifiant MainWindow.")
                main_window._on_item_manipulated(self) # Met à jour les spinboxes

            event.accept()
            return

        super().mouseReleaseEvent(event)

class CanvasView(QGraphicsView):
    """
    Vue personnalisée pour gérer le zoom et le dézoom.
    """
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag) # Permet de "tirer" la scène
        self.zoom_factor_base = 1.1

    def wheelEvent(self, event):
        # Zoom avec la molette de la souris
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            angle = event.angleDelta().y()
            if angle > 0:
                self.scale_view(self.zoom_factor_base)
            else:
                self.scale_view(1 / self.zoom_factor_base)
        else:
            super().wheelEvent(event) # Comportement par défaut (scroll)

    def scale_view(self, factor):
        self.scale(factor, factor)

    def zoom_in(self):
        self.scale_view(self.zoom_factor_base * 1.5)

    def zoom_out(self):
        self.scale_view(1 / (self.zoom_factor_base * 1.5))

    def reset_zoom(self):
        self.resetTransform()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Application de Composition d'Images")
        self.setGeometry(100, 100, 1200, 800)

        self.image_items = [] # Liste pour stocker les DraggableResizablePixmapItem
        self.active_item = None
        self.is_precise_mode = False

        self._setup_ui()
        self._create_actions()
        self._create_toolbars()
        self._create_menus() # Optionnel, mais bien pour les raccourcis
        self._connect_signals()

        self.update_controls_state() # Initial state of controls

    def _setup_ui(self):
        # Zone de travail principale
        self.scene = QGraphicsScene(self)
        self.scene.setBackgroundBrush(QColor(220, 220, 220)) # Fond gris clair
        self.view = CanvasView(self.scene, self)
        self.setCentralWidget(self.view)

        # Panneau latéral pour les miniatures (Dock Widget)
        self.thumbnail_dock = QDockWidget("Images Importées", self)
        self.thumbnail_list_widget = QListWidget()
        self.thumbnail_list_widget.setIconSize(QSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE))
        #self.thumbnail_list_widget.setViewMode(QListWidget.ViewMode.IconMode) # Ou ListMode
        self.thumbnail_list_widget.setViewMode(QListWidget.ViewMode.ListMode) # TEST
        self.thumbnail_list_widget.setFlow(QListWidget.Flow.TopToBottom)
        #self.thumbnail_list_widget.setMovement(QListWidget.Movement.Static) # Empêche le drag & drop interne

         # Activer le Drag & Drop
        self.thumbnail_list_widget.setDragEnabled(True)
        self.thumbnail_list_widget.setAcceptDrops(True)
        self.thumbnail_list_widget.setDropIndicatorShown(True)
        # QListWidget.InternalMove permet de réorganiser les items à l'intérieur du même widget
        self.thumbnail_list_widget.setDefaultDropAction(Qt.DropAction.MoveAction) # Indique que c'est un déplacement
        self.thumbnail_list_widget.setMovement(QListWidget.Movement.Snap) # Ou Free, Snap est bien pour les listes

        self.thumbnail_list_widget.setMinimumWidth(THUMBNAIL_SIZE + 40) # AJOUTER : taille icône + marges
        self.thumbnail_list_widget.setMinimumHeight(300) # AJOUTER : pour voir plusieurs items
        self.thumbnail_dock.setWidget(self.thumbnail_list_widget)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.thumbnail_dock)
        self.thumbnail_dock.setVisible(True) # Assurer qu'il est visible
        self.thumbnail_dock.setFloating(False) # S'assurer qu'il n'est pas flottant et potentiellement hors écran
        # Redimensionner la QMainWindow pour forcer le recalcul du layout des docks
        # self.resize(self.width()+1, self.height()) # Astuce parfois utile
        # self.resize(self.width()-1, self.height())
        print(f"[DEBUG] _setup_ui: thumbnail_dock visible: {self.thumbnail_dock.isVisible()}, floating: {self.thumbnail_dock.isFloating()}")
        print(f"[DEBUG] _setup_ui: thumbnail_dock geometry: {self.thumbnail_dock.geometry()}")
        print(f"[DEBUG] _setup_ui: thumbnail_list_widget geometry (dans dock): {self.thumbnail_list_widget.geometry()}")

        # Panneau de contrôle (Dock Widget)
        self.controls_dock = QDockWidget("Contrôles de l'Image", self)
        controls_widget = QWidget()
        controls_layout = QFormLayout(controls_widget)

        self.precise_mode_checkbox = QCheckBox("Mode Précis")
        controls_layout.addRow(self.precise_mode_checkbox)

        self.rotation_spinbox = QDoubleSpinBox()
        self.rotation_spinbox.setRange(-360, 360)
        self.rotation_spinbox.setSuffix(" °")
        controls_layout.addRow("Rotation:", self.rotation_spinbox)

        self.scale_spinbox = QDoubleSpinBox()
        self.scale_spinbox.setRange(0.01, 10.0)
        self.scale_spinbox.setSingleStep(0.1)
        self.scale_spinbox.setDecimals(2)
        self.scale_spinbox.setValue(1.0)
        controls_layout.addRow("Échelle:", self.scale_spinbox)

        self.controls_dock.setWidget(controls_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.controls_dock)


        # Barre de statut
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.active_image_label = QLabel("Aucune image active")
        self.status_bar.addPermanentWidget(self.active_image_label)

    def _create_actions(self):
        self.import_action = QAction("&Importer Images...", self,
                                     shortcut=QKeySequence.StandardKey.Open,
                                     statusTip="Importer des images (2 à 6)",
                                     triggered=self.import_images)
        self.export_action = QAction("&Exporter Composition...", self,
                                     shortcut=QKeySequence.StandardKey.Save,
                                     statusTip="Exporter l'image composite",
                                     triggered=self.export_composition)
        self.quit_action = QAction("&Quitter", self,
                                   shortcut=QKeySequence.StandardKey.Quit,
                                   statusTip="Quitter l'application",
                                   triggered=self.close)
        self.zoom_in_action = QAction("Zoom &Avant", self,
                                      shortcut=QKeySequence.StandardKey.ZoomIn,
                                      triggered=self.view.zoom_in)
        self.zoom_out_action = QAction("Zoom A&rrière", self,
                                       shortcut=QKeySequence.StandardKey.ZoomOut,
                                       triggered=self.view.zoom_out)
        self.reset_zoom_action = QAction("Zoom &Normal", self,
                                         shortcut="Ctrl+0",
                                         triggered=self.view.reset_zoom)

    def _create_toolbars(self):
        # Barre d'outils Fichier
        file_toolbar = self.addToolBar("Fichier")
        file_toolbar.addAction(self.import_action)
        file_toolbar.addAction(self.export_action)

        # Barre d'outils Vue
        view_toolbar = self.addToolBar("Vue")
        view_toolbar.addAction(self.zoom_in_action)
        view_toolbar.addAction(self.zoom_out_action)
        view_toolbar.addAction(self.reset_zoom_action)

    def _create_menus(self):
        # Menu Fichier
        file_menu = self.menuBar().addMenu("&Fichier")
        file_menu.addAction(self.import_action)
        file_menu.addAction(self.export_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)

        # Menu Vue
        view_menu = self.menuBar().addMenu("&Vue")
        view_menu.addAction(self.zoom_in_action)
        view_menu.addAction(self.zoom_out_action)
        view_menu.addAction(self.reset_zoom_action)

    def _on_scene_selection_changed(self):
        print("[DEBUG] _on_scene_selection_changed: Signal reçu.")
        selected_items = self.scene.selectedItems()
        if selected_items:
            # Prendre le premier item sélectionné (normalement un seul avec ItemIsSelectable)
            # S'assurer que c'est bien un de nos items d'image
            active_candidate = selected_items[0]
            if isinstance(active_candidate, DraggableResizablePixmapItem):
                print(f"[DEBUG] _on_scene_selection_changed: Item sélectionné: {active_candidate.filename}")
                if self.active_item != active_candidate: # Si c'est un nouvel item
                    self._set_active_item(active_candidate)
                    # Mettre à jour la sélection dans la liste des miniatures
                    for i in range(self.thumbnail_list_widget.count()):
                        list_item = self.thumbnail_list_widget.item(i)
                        if list_item.data(Qt.ItemDataRole.UserRole) == active_candidate:
                            self.thumbnail_list_widget.setCurrentItem(list_item, QItemSelectionModel.SelectionFlag.ClearAndSelect) # S'assurer qu'il est bien sélectionné
                            print(f"[DEBUG] _on_scene_selection_changed: Miniature {i} sélectionnée pour {active_candidate.filename}")
                            break
            else:
                print(f"[DEBUG] _on_scene_selection_changed: Item sélectionné n'est pas un DraggableResizablePixmapItem: {type(active_candidate)}")
        else:
            print("[DEBUG] _on_scene_selection_changed: Aucun item sélectionné. Désactivation de l'item actif.")
            self._set_active_item(None)
        self.update_controls_state() # Mettre à jour les contrôles dans tous les cas

    def _connect_signals(self):
        self.thumbnail_list_widget.itemClicked.connect(self._on_thumbnail_clicked)
        # Connecter au signal rowsMoved du modèle du QListWidget
        self.thumbnail_list_widget.model().rowsMoved.connect(self._on_thumbnail_order_changed)

        self.precise_mode_checkbox.stateChanged.connect(self._on_precise_mode_changed)
        self.rotation_spinbox.valueChanged.connect(self._on_rotation_changed)
        self.scale_spinbox.valueChanged.connect(self._on_scale_changed)
        self.scene.selectionChanged.connect(self._on_scene_selection_changed)

    # Dans MainWindow
    def _on_thumbnail_order_changed(self, parent_index, start_row, end_row, destination_index, dest_row):
        """
        Appelé lorsque l'ordre des items dans la liste des miniatures est modifié
        par drag & drop.
        Met à jour le Z-order des QGraphicsPixmapItem correspondants.
        """
        print(f"[DEBUG] _on_thumbnail_order_changed: Rows moved from {start_row}-{end_row} to {dest_row}")
        self.update_z_order_from_thumbnails()

    def update_z_order_from_thumbnails(self):
        """
        Met à jour le Z-order des images sur la scène en fonction de l'ordre
        actuel des items dans la liste des miniatures.
        L'item en haut de la liste (index 0) est le plus en arrière (Z le plus bas).
        L'item en bas de la liste est le plus en avant (Z le plus haut).
        """
        if not self.image_items: # S'il n'y a pas d'image_items (qui sont les DraggableResizablePixmapItem)
            return

        num_thumbnails = self.thumbnail_list_widget.count()
        if num_thumbnails == 0:
            return

        print("[DEBUG] update_z_order_from_thumbnails: Mise à jour du Z-order...")

        # Créer une liste temporaire des graphic_items dans le nouvel ordre des miniatures
        ordered_graphic_items = []
        for i in range(num_thumbnails):
            list_item = self.thumbnail_list_widget.item(i)
            if list_item:
                graphic_item = list_item.data(Qt.ItemDataRole.UserRole)
                if graphic_item and isinstance(graphic_item, DraggableResizablePixmapItem):
                    ordered_graphic_items.append(graphic_item)
                else:
                    print(f"[AVERTISSEMENT] update_z_order_from_thumbnails: Item de liste à l'index {i} n'a pas de graphic_item valide.")
            else:
                print(f"[AVERTISSEMENT] update_z_order_from_thumbnails: Impossible de récupérer l'item de liste à l'index {i}.")


        # Assigner les Z-values. Z=0.0 est l'arrière-plan par défaut.
        # On peut commencer à Z=1.0 pour nos items.
        # Il est important que les Z-values soient distincts si on veut un ordre strict.
        for i, graphic_item in enumerate(ordered_graphic_items):
            # i=0 est l'item le plus en haut de la liste (le plus en arrière)
            # i=len-1 est l'item le plus en bas (le plus en avant)
            # QGraphicsItem avec Z plus grand est dessiné par-dessus ceux avec Z plus petit.
            # Donc, l'item en bas de la liste (dernier dans ordered_graphic_items) doit avoir le Z le plus élevé.
            # L'item en haut de la liste (premier dans ordered_graphic_items) doit avoir le Z le plus bas.
            new_z_value = float(i + 1) # Z = 1.0, 2.0, 3.0 ...
            graphic_item.setZValue(new_z_value)
            print(f"[DEBUG] update_z_order_from_thumbnails: Item '{graphic_item.filename}' mis à Z-value {new_z_value}")

        # S'assurer que l'item actif (s'il y en a un) reste visuellement "sélectionné"
        # et potentiellement au-dessus des autres temporairement lors d'une interaction directe.
        # La logique actuelle de _set_active_item et mousePressEvent sur l'item
        # gère déjà le fait de mettre l'item actif au premier plan lors de l'interaction.
        # Cette fonction `update_z_order_from_thumbnails` définit l'ordre de base.
        # Si un item est actif, sa logique de mise au premier plan temporaire prévaudra
        # sur le Z-value de base jusqu'à ce qu'il soit désactivé ou qu'un autre soit activé.

        self.scene.update() # Forcer une mise à jour de la scène si nécessaire




    def update_controls_state(self):
        """ Met à jour l'état (activé/désactivé) des contrôles en fonction de l'image active. """
        is_item_active = self.active_item is not None
        self.rotation_spinbox.setEnabled(is_item_active)
        self.scale_spinbox.setEnabled(is_item_active)

        if is_item_active:
            # Bloquer les signaux pour éviter les mises à jour en boucle
            self.rotation_spinbox.blockSignals(True)
            self.scale_spinbox.blockSignals(True)

            self.rotation_spinbox.setValue(self.active_item.rotation())
            self.scale_spinbox.setValue(self.active_item.scale())

            self.rotation_spinbox.blockSignals(False)
            self.scale_spinbox.blockSignals(False)
        else:
            self.rotation_spinbox.setValue(0)
            self.scale_spinbox.setValue(1.0)

    def import_images(self):
        print("[DEBUG] import_images: Fonction appelée.")

        file_dialog = QFileDialog(self)
        file_dialog.setNameFilter("Images (*.png *.jpg *.jpeg *.bmp)")
        # Permettre la sélection multiple
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)

        if file_dialog.exec():
            filenames = file_dialog.selectedFiles()
            print(f"[DEBUG] import_images: Fichiers sélectionnés: {filenames}")

            if not filenames:
                print("[DEBUG] import_images: Aucun fichier sélectionné.")
                self.status_bar.showMessage("Aucun fichier n'a été sélectionné.", 3000)
                return

            if not (MIN_IMAGES <= len(filenames) <= MAX_IMAGES):
                print(f"[DEBUG] import_images: Nombre de fichiers ({len(filenames)}) hors des limites ({MIN_IMAGES}-{MAX_IMAGES}).")
                self.status_bar.showMessage(
                    f"Veuillez sélectionner entre {MIN_IMAGES} et {MAX_IMAGES} images.", 5000
                )
                return

            # Effacer les images précédentes SEULEMENT si de nouvelles images valides sont sélectionnées
            self.clear_all_images()
            print("[DEBUG] import_images: Anciennes images effacées (appel de clear_all_images).")

            successful_imports = 0
            for i, filename in enumerate(filenames):
                print(f"[DEBUG] import_images: Traitement de l'image {i+1}/{len(filenames)}: {filename}")
                try:
                    # Essayer de lire avec une méthode plus robuste pour les chemins sous Windows
                    # np_array_img = np.fromfile(filename, np.uint8)
                    # cv_image = cv2.imdecode(np_array_img, cv2.IMREAD_COLOR)
                    # Ou la méthode standard:
                    cv_image = cv2.imread(filename)

                    if cv_image is None:
                        print(f"[ERREUR] import_images: cv2.imread (ou imdecode) a retourné None pour {filename}. Vérifiez le chemin et le fichier.")
                        # Essayer avec imread et encodage si le chemin contient des non-ASCII (plus pour Linux/Mac)
                        # try:
                        #     cv_image = cv2.imread(filename.encode(sys.getfilesystemencoding()))
                        #     if cv_image is None:
                        #          raise IOError(f"Impossible de charger l'image {filename} (même avec encodage).")
                        # except Exception as enc_e:
                        #     print(f"[ERREUR] Échec du chargement avec encodage pour {filename}: {enc_e}")
                        raise IOError(f"Impossible de charger l'image {filename} avec OpenCV. L'image est peut-être corrompue ou le format n'est pas supporté.")

                    print(f"[DEBUG] import_images: Image {filename} chargée par OpenCV. Dimensions: {cv_image.shape}")

                    # Convertir BGR (OpenCV) en RGB (Qt)
                    # S'assurer que l'image a 3 canaux (BGR) avant de convertir en RGB
                    if len(cv_image.shape) == 2: # Image en niveaux de gris
                        print(f"[INFO] import_images: Image {filename} est en niveaux de gris. Conversion en BGR.")
                        cv_image = cv2.cvtColor(cv_image, cv2.COLOR_GRAY2BGR)
                    elif cv_image.shape[2] == 4: # Image BGRA
                        print(f"[INFO] import_images: Image {filename} a un canal alpha (BGRA). Conversion en BGR.")
                        cv_image = cv2.cvtColor(cv_image, cv2.COLOR_BGRA2BGR)
                    
                    # Maintenant, cv_image devrait être BGR
                    rgb_image = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb_image.shape
                    bytes_per_line = ch * w
                    
                    # Il est crucial que les données de rgb_image.data restent valides.
                    # QImage peut ne pas copier les données immédiatement.
                    # Pour être sûr, on peut faire une copie des données pour QImage.
                    # Mais QPixmap.fromImage() fait généralement une copie profonde.
                    q_image_data_copy = rgb_image.copy() # Garde les données en vie
                    q_image = QImage(q_image_data_copy.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                    
                    if q_image.isNull():
                        print(f"[ERREUR] import_images: QImage est nulle pour {filename} après conversion.")
                        raise ValueError("La QImage créée est nulle.")
                    pixmap = QPixmap.fromImage(q_image)
                    if pixmap.isNull():
                        print(f"[ERREUR] import_images: QPixmap est nulle pour {filename} après QPixmap.fromImage.")
                        raise ValueError("La QPixmap créée est nulle.")

                    print(f"[DEBUG] import_images: Pixmap créé pour {filename}. Taille: {pixmap.size()}. Est nul: {pixmap.isNull()}")

                    # Créer l'item graphique
                    item = DraggableResizablePixmapItem(pixmap, os.path.basename(filename), cv_image) # cv_image est l'original (potentiellement modifié GRAY->BGR)
                    self.image_items.append(item)
                    self.scene.addItem(item) # Ajout à la scène graphique
                    print(f"[DEBUG] import_images: Item graphique ajouté à la scène pour {filename}. Nombre d'items dans la scène: {len(self.scene.items())}")

                    # Positionner initialement en cascade
                    item.setPos(i * 20, i * 20)
                    print(f"[DEBUG] import_images: Item positionné à ({i*20}, {i*20}). BoundingRect de l'item: {item.boundingRect()}")

                    # Créer la miniature
                    thumbnail_pixmap = pixmap.scaled(THUMBNAIL_SIZE, THUMBNAIL_SIZE,
                                                     Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation)
                    print(f"[DEBUG] import_images: Thumbnail pixmap créé. Taille: {thumbnail_pixmap.size()}, Est nul: {thumbnail_pixmap.isNull()}")
                    list_item = QListWidgetItem(QIcon(thumbnail_pixmap), os.path.basename(filename))
                    list_item.setData(Qt.ItemDataRole.UserRole, item)
                    self.thumbnail_list_widget.addItem(list_item) # Ajout à la liste des miniatures
                    print(f"[DEBUG] import_images: Miniature ajoutée à la liste pour {filename}. Nombre d'items dans la liste: {self.thumbnail_list_widget.count()}")
                    successful_imports += 1

                except Exception as e:
                    self.status_bar.showMessage(f"Erreur importation {filename}: {e}", 7000)
                    print(f"[ERREUR PROFONDE] import_images: Exception lors de l'importation de {filename}: {e}")
                    import traceback
                    traceback.print_exc() # Imprime la trace complète de l'exception

            if successful_imports > 0:
                print(f"[DEBUG] import_images: {successful_imports} image(s) importée(s) avec succès. Sélection de la première.")
                self._set_active_item(self.image_items[0]) # image_items[0] est le premier Draggable...
                self.thumbnail_list_widget.setCurrentRow(0)
                self.update_z_order_from_thumbnails() # << AJOUTER CET APPEL ICI
            else:
                print("[DEBUG] import_images: Aucune image n'a été importée avec succès.")

            # Ajuster la vue à la scène après que tous les items y ont été ajoutés et positionnés
            current_scene_rect = self.scene.itemsBoundingRect()
            self.view.setSceneRect(current_scene_rect)
            print(f"[DEBUG] import_images: SceneRect mis à jour: {current_scene_rect}. La vue devrait se recadrer.")
            print(f"[DEBUG] import_images: Nombre total d'items dans la scène à la fin: {len(self.scene.items())}")
            # Forcer une mise à jour de la vue si nécessaire
            self.view.viewport().update()
        else:
            print("[DEBUG] import_images: Dialogue d'importation annulé ou fermé.")
            print(f"[DEBUG] import_images (fin): thumbnail_dock visible: {self.thumbnail_dock.isVisible()}")
            print(f"[DEBUG] import_images (fin): thumbnail_dock geometry: {self.thumbnail_dock.geometry()}")
            print(f"[DEBUG] import_images (fin): thumbnail_list_widget count: {self.thumbnail_list_widget.count()}")
            print(f"[DEBUG] import_images (fin): thumbnail_list_widget item(0) text (si existe): {self.thumbnail_list_widget.item(0).text() if self.thumbnail_list_widget.count() > 0 else 'N/A'}")
            # Forcer une mise à jour du layout du dock widget
            self.thumbnail_dock.updateGeometry()
            self.thumbnail_list_widget.updateGeometry()
            # self.thumbnail_list_widget.adjustSize() # Peut aider

    def clear_all_images(self):
        print("[DEBUG] clear_all_images: Fonction appelée.")
        if self.active_item:
            self.active_item.setSelected(False)
            self._set_active_item(None)

        # Copier la liste pour itération sûre si removeItem modifie la source (ce n'est pas le cas pour scene.removeItem)
        items_to_remove = list(self.image_items)
        for item in items_to_remove:
            if item.scene() == self.scene:
                 self.scene.removeItem(item)
                 print(f"[DEBUG] clear_all_images: Item {item.filename} supprimé de la scène.")

        self.image_items.clear()
        print("[DEBUG] clear_all_images: self.image_items vidé.")
        self.thumbnail_list_widget.clear()
        print("[DEBUG] clear_all_images: thumbnail_list_widget vidé.")
        # self.scene.clearSelection() # Au cas où
        print("[DEBUG] clear_all_images: Terminé.")

    def _on_thumbnail_clicked(self, list_item):
        graphic_item = list_item.data(Qt.ItemDataRole.UserRole)
        if graphic_item and isinstance(graphic_item, DraggableResizablePixmapItem):
            print(f"[DEBUG] _on_thumbnail_clicked: Miniature cliquée pour {graphic_item.filename}")
            # Déselectionner tous les autres items dans la scène avant de sélectionner le nouveau
            # pour s'assurer que selectionChanged est bien émis si l'item était déjà le seul sélectionné.
            # Ou plus simple, juste s'assurer que cet item est sélectionné.
            # self.scene.clearSelection() # Optionnel, peut être un peu agressif
            graphic_item.setSelected(True) # Ceci devrait déclencher scene.selectionChanged
            # _set_active_item sera appelé par _on_scene_selection_changed
            print(f"[DEBUG] _on_thumbnail_clicked: Item {graphic_item.filename} marqué comme sélectionné dans la scène.")
        else:
            print("[DEBUG] _on_thumbnail_clicked: Item de liste cliqué n'a pas de graphic_item valide ou n'est pas DraggableResizablePixmapItem.")


    def _set_active_item(self, new_item):
        print(f"[DEBUG] _set_active_item: Tentative de définir actif: {new_item.filename if new_item else 'None'}")

        # Rétablir l'opacité de l'ancien item actif s'il existe et est valide
        if self.active_item and self.active_item != new_item:
            if isinstance(self.active_item, DraggableResizablePixmapItem):
                self.active_item.set_active(False)
                self.active_item.setSelected(False)
                self.active_item.set_interactive_opacity(False) # Rétablir l'opacité
                print(f"[DEBUG] _set_active_item: Ancien item {self.active_item.filename} désactivé, désélectionné, opacité rétablie.")

        old_active_item_ref = self.active_item
        self.active_item = new_item

        if self.active_item:
            if not isinstance(self.active_item, DraggableResizablePixmapItem):
                print(f"[ERREUR] _set_active_item: Tentative de définir actif un item qui n'est pas DraggableResizablePixmapItem: {type(self.active_item)}")
                self.active_item = old_active_item_ref # Revenir en arrière
                return

            self.active_item.set_active(True) # Pour le contour rouge
            if not self.active_item.isSelected():
                self.active_item.setSelected(True) # Sélectionner dans la scène
                print(f"[DEBUG] _set_active_item: Item {self.active_item.filename} sélectionné dans la scène.")
            else:
                print(f"[DEBUG] _set_active_item: Item {self.active_item.filename} était déjà sélectionné.")

            self.active_item.set_interactive_opacity(True) # Mettre l'item actif en semi-transparent
            print(f"[DEBUG] _set_active_item: Item {self.active_item.filename} mis en opacité interactive.")

            self.active_image_label.setText(f"Active: {self.active_item.filename}")

            if self.active_item.scene():
                other_pixmap_items_z = [
                    itm.zValue() for itm in self.active_item.scene().items()
                    if isinstance(itm, DraggableResizablePixmapItem) and itm is not self.active_item
                ]
                new_z = (max(other_pixmap_items_z) + 1) if other_pixmap_items_z else 1.0
                self.active_item.setZValue(new_z)
                print(f"[DEBUG] _set_active_item: Item {self.active_item.filename} mis au Z-value {new_z}.")
        else:
            self.active_image_label.setText("Aucune image active")
            print("[DEBUG] _set_active_item: Aucune image active définie.")

        self.update_controls_state()

    def _on_precise_mode_changed(self, state):
        self.is_precise_mode = state == Qt.CheckState.Checked.value # Pour Qt6
        # Ou pour Qt5/compatibilité: self.is_precise_mode = state == Qt.Checked
        mode_str = "Précis" if self.is_precise_mode else "Rapide"
        self.status_bar.showMessage(f"Mode de réglage: {mode_str}", 2000)
        print(f"[DEBUG] MainWindow: Mode précis activé: {self.is_precise_mode}") # Pour vérifier

    def _on_rotation_changed(self, value):
        if self.active_item and not self.rotation_spinbox.signalsBlocked():
            self.active_item.setRotation(value)

    def _on_scale_changed(self, value):
        if self.active_item and not self.scale_spinbox.signalsBlocked():
            # Assurer que l'échelle ne devienne pas nulle ou négative
            if value > 0:
                self.active_item.setScale(value)


    def keyPressEvent(self, event):
        if not self.active_item:
            super().keyPressEvent(event)
            return

        move_step = STEP_PRECISE_MOVE if self.is_precise_mode else STEP_QUICK_MOVE
        scale_step = STEP_PRECISE_SCALE if self.is_precise_mode else STEP_QUICK_SCALE
        rotate_step = STEP_PRECISE_ROTATE if self.is_precise_mode else STEP_QUICK_ROTATE

        key = event.key()

        # Mouvement
        if key == Qt.Key.Key_Up:
            self.active_item.moveBy(0, -move_step)
        elif key == Qt.Key.Key_Down:
            self.active_item.moveBy(0, move_step)
        elif key == Qt.Key.Key_Left:
            self.active_item.moveBy(-move_step, 0)
        elif key == Qt.Key.Key_Right:
            self.active_item.moveBy(move_step, 0)

        # Rotation (ex: avec R et T, ou PageUp/PageDown)
        elif key == Qt.Key.Key_R: # Rotation horaire
            new_rotation = self.active_item.rotation() + rotate_step
            self.active_item.setRotation(new_rotation)
            self.rotation_spinbox.setValue(new_rotation % 360) # Mettre à jour spinbox
        elif key == Qt.Key.Key_E: # Rotation anti-horaire (E comme 'Everse')
            new_rotation = self.active_item.rotation() - rotate_step
            self.active_item.setRotation(new_rotation)
            self.rotation_spinbox.setValue(new_rotation % 360)

        # Échelle (ex: avec + et -)
        elif key == Qt.Key.Key_Plus or key == Qt.Key.Key_Equal: # Souvent ensemble sur les claviers
            current_scale = self.active_item.scale()
            new_scale = max(0.01, current_scale + scale_step) # Empêcher échelle <= 0
            self.active_item.setScale(new_scale)
            self.scale_spinbox.setValue(new_scale)
        elif key == Qt.Key.Key_Minus:
            current_scale = self.active_item.scale()
            new_scale = max(0.01, current_scale - scale_step)
            self.active_item.setScale(new_scale)
            self.scale_spinbox.setValue(new_scale)

        # Naviguer entre les images avec Tab / Shift+Tab
        elif key == Qt.Key.Key_Tab:
            self.select_next_image()
        elif key == Qt.Key.Key_Backtab: # Shift+Tab
            self.select_previous_image()

        else:
            super().keyPressEvent(event) # Laisser les autres touches être gérées normalement

        self.update_controls_state() # Mettre à jour les spinbox après modif clavier

    def select_next_image(self):
        if not self.image_items: return
        current_index = -1
        if self.active_item:
            try:
                current_index = self.image_items.index(self.active_item)
            except ValueError: # Au cas où l'item actif n'est plus dans la liste (ne devrait pas arriver)
                pass
        next_index = (current_index + 1) % len(self.image_items)
        self._set_active_item(self.image_items[next_index])
        self.thumbnail_list_widget.setCurrentRow(next_index)

    def select_previous_image(self):
        if not self.image_items: return
        current_index = 0
        if self.active_item:
            try:
                current_index = self.image_items.index(self.active_item)
            except ValueError:
                pass
        prev_index = (current_index - 1 + len(self.image_items)) % len(self.image_items)
        self._set_active_item(self.image_items[prev_index])
        self.thumbnail_list_widget.setCurrentRow(prev_index)

    def export_composition(self):
        if not self.image_items:
            self.status_bar.showMessage("Aucune image à exporter.", 3000)
            return

        # Déterminer la zone à exporter. On prend le rectangle englobant tous les items.
        # Pour une "haute résolution", il faudrait idéalement retravailler avec les images OpenCV originales.
        # Pour l'instant, on exporte ce qui est visible dans la scène.
        export_rect = self.scene.itemsBoundingRect()
        if export_rect.isEmpty():
            self.status_bar.showMessage("La scène est vide.", 3000)
            return

        # S'assurer que les dimensions ne sont pas trop grandes pour QImage,
        # ou gérer cela par tuiles si nécessaire pour de très grandes images.
        # Pour l'instant, on suppose que ça tient en mémoire.

        # Créer une image de la taille du rectangle englobant
        target_image = QImage(export_rect.size().toSize(), QImage.Format.Format_ARGB32_Premultiplied)
        target_image.fill(Qt.GlobalColor.transparent) # Fond transparent

        painter = QPainter(target_image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Rendre la scène sur notre image. La source est export_rect, la target est le QRect(0,0, w,h) de l'image
        self.scene.render(painter, QRectF(target_image.rect()), export_rect)
        painter.end()

        # Sauvegarder l'image
        filePath, _ = QFileDialog.getSaveFileName(
            self, "Exporter l'Image Composite", "", "PNG Image (*.png);;JPEG Image (*.jpg)"
        )

        if filePath:
            if not target_image.save(filePath):
                self.status_bar.showMessage(f"Erreur lors de la sauvegarde de l'image: {filePath}", 5000)
            else:
                self.status_bar.showMessage(f"Image sauvegardée: {filePath}", 3000)

    def closeEvent(self, event):
        # Ici, vous pourriez ajouter une confirmation si des modifications non sauvegardées existent
        super().closeEvent(event)

    def _on_item_manipulated(self, item):
        """Appelé lorsque l'item actif est manipulé par des actions personnalisées."""
        if item == self.active_item:
            print(f"[DEBUG] MainWindow: _on_item_manipulated pour {item.filename}")
            self.update_controls_state() # Cela mettra à jour les spinbox

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())