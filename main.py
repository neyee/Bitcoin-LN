<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Radio en Vivo</title>
    <style>
        /* Estilos Generales */
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #222; /* Fondo oscuro */
            color: #fff;
            margin: 0;
            padding: 0;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
        }

        .container {
            background-color: rgba(255, 255, 255, 0.1); /* Contenedor semitransparente */
            border-radius: 15px;
            padding: 30px;
            text-align: center;
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.3);
            max-width: 600px;
            width: 90%;
        }

        h1 {
            color: #fff;
            margin-bottom: 20px;
            font-size: 2.5em;
            text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.5);
        }

        p {
            font-size: 1.1em;
            line-height: 1.6;
            color: #ddd;
            margin-bottom: 30px;
        }

        /* Estilos del Reproductor de Audio */
        audio {
            width: 100%;
            max-width: 400px;
            border-radius: 5px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
        }

        /* Estilos del Botón de Redes Sociales (Ejemplo) */
        .social-button {
            display: inline-block;
            padding: 12px 24px;
            background-color: #007bff; /* Azul */
            color: #fff;
            text-decoration: none;
            border-radius: 8px;
            font-weight: bold;
            transition: background-color 0.3s ease;
        }

        .social-button:hover {
            background-color: #0056b3; /* Azul más oscuro al pasar el ratón */
        }

         /* Animación sutil para el fondo */
        @keyframes backgroundAnimation {
            0% {
                background-position: 0% 50%;
            }
            50% {
                background-position: 100% 50%;
            }
            100% {
                background-position: 0% 50%;
            }
        }

        body {
            background: linear-gradient(270deg, #1e272c, #2e343a, #3d454c);
            background-size: 300% 300%;
            animation: backgroundAnimation 15s ease infinite;
        }


    </style>
</head>
<body>
    <div class="container">
        <h1>¡Escucha Radio XYZ en Vivo!</h1>
        <p>Sintoniza nuestra transmisión en vivo y disfruta de la mejor música, noticias y entretenimiento.</p>
        <audio controls autoplay>
            <source src="URL_DE_TU_STREAM_AQUI" type="audio/mpeg">
            Tu navegador no soporta la reproducción de audio.
        </audio>
        <p>Síguenos en nuestras redes sociales:</p>
        <a href="#" class="social-button">Facebook</a>
        <a href="#" class="social-button">Twitter</a>
        <a href="#" class="social-button">Instagram</a>
    </div>
</body>
</html>
