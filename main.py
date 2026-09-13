from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button


class PantallaPrincipal(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=40, spacing=20, **kwargs)
        self.mensaje = Label(text="Hola Juan -- Fase 0 funcionando.", font_size=24)
        self.add_widget(self.mensaje)
        boton = Button(text="Tócame", size_hint=(1, 0.3), font_size=20)
        boton.bind(on_press=self.al_tocar)
        self.add_widget(boton)

    def al_tocar(self, instance):
        self.mensaje.text = "¡El APK sí funciona de verdad!"


class JoiApp(App):
    def build(self):
        return PantallaPrincipal()


if __name__ == "__main__":
    JoiApp().run()
